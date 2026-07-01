from __future__ import annotations

import logging
import os
import time
from collections import Counter
from typing import Any, Dict, List, Optional, TypedDict

import litellm
from litellm import completion

logger = logging.getLogger(__name__)

litellm.set_verbose = False


# ---------------------------------------------------------------------------
# OpenRouter rate limits (free tier)
# ---------------------------------------------------------------------------

OPENROUTER_FREE_REQ_PER_MIN = 20
OPENROUTER_FREE_REQ_PER_DAY = 200
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_WINDOW_DAILY = 86400


# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------

class ModelConfig(TypedDict):
    model: str
    env_key: str


_MODELS_REGISTRY: Dict[str, ModelConfig] = {
    "gemini-2.0-flash": {"model": "openrouter/google/gemini-2.0-flash-exp:free", "env_key": "OPENROUTER_API_KEY"},
    "llama-3.3-70b": {"model": "openrouter/meta-llama/llama-3.3-70b-instruct:free", "env_key": "OPENROUTER_API_KEY"},
    "qwen-2.5-coder": {"model": "openrouter/qwen/qwen-2.5-coder-32b-instruct:free", "env_key": "OPENROUTER_API_KEY"},
    "llama-3.1-8b": {"model": "openrouter/meta-llama/llama-3.1-8b-instruct:free", "env_key": "OPENROUTER_API_KEY"},
    "llama-3.2-3b": {"model": "openrouter/meta-llama/llama-3.2-3b-instruct:free", "env_key": "OPENROUTER_API_KEY"},
}


# ---------------------------------------------------------------------------
# Task → model assignments (spread load across models)
# ---------------------------------------------------------------------------

_TASK_MODELS: Dict[str, List[str]] = {
    "intent_classification": ["llama-3.3-70b", "gemini-2.0-flash", "llama-3.1-8b"],
    "context_keyword_generation": ["llama-3.3-70b", "gemini-2.0-flash", "llama-3.1-8b"],
    "product_extraction": ["gemini-2.0-flash", "llama-3.3-70b", "qwen-2.5-coder"],
    "response_generation": ["gemini-2.0-flash", "llama-3.3-70b", "llama-3.1-8b"],
    "comparison": ["gemini-2.0-flash", "llama-3.3-70b", "qwen-2.5-coder"],
    "summarization": ["llama-3.2-3b", "llama-3.1-8b", "gemini-2.0-flash"],
}


# ---------------------------------------------------------------------------
# Task profiles (default params per task)
# ---------------------------------------------------------------------------

class TaskProfile(TypedDict):
    model_keys: List[str]
    default_params: Dict[str, Any]


_TASK_PROFILES: Dict[str, TaskProfile] = {
    "intent_classification": {
        "model_keys": _TASK_MODELS["intent_classification"],
        "default_params": {"temperature": 0.1, "max_tokens": 1024},
    },
    "context_keyword_generation": {
        "model_keys": _TASK_MODELS["context_keyword_generation"],
        "default_params": {"temperature": 0.2, "max_tokens": 1024},
    },
    "product_extraction": {
        "model_keys": _TASK_MODELS["product_extraction"],
        "default_params": {"temperature": 0.1, "max_tokens": 8192},
    },
    "response_generation": {
        "model_keys": _TASK_MODELS["response_generation"],
        "default_params": {"temperature": 0.3, "max_tokens": 2048},
    },
    "comparison": {
        "model_keys": _TASK_MODELS["comparison"],
        "default_params": {"temperature": 0.3, "max_tokens": 4096},
    },
    "summarization": {
        "model_keys": _TASK_MODELS["summarization"],
        "default_params": {"temperature": 0.3, "max_tokens": 2048},
    },
}


# ---------------------------------------------------------------------------
# Rate-limit tracking
# ---------------------------------------------------------------------------

COOLDOWN_SECONDS = 30
MAX_INPUT_CHARS = 6000  # ~2000 tokens — chunk if larger


class ModelStats:
    __slots__ = ("success_count", "rate_limit_count", "error_count",
                 "prompt_tokens", "completion_tokens", "total_tokens",
                 "last_call_at", "last_error_at", "last_error_msg")

    def __init__(self) -> None:
        self.success_count: int = 0
        self.rate_limit_count: int = 0
        self.error_count: int = 0
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0
        self.total_tokens: int = 0
        self.last_call_at: Optional[float] = None
        self.last_error_at: Optional[float] = None
        self.last_error_msg: Optional[str] = None


class LLMGateway:
    def __init__(self) -> None:
        self._task_profiles = _TASK_PROFILES
        # Round-robin: per-task count per model key
        self._usage: Counter = Counter()
        # Cooldown: model_key -> timestamp until which it's skipped
        self._cooldowns: Dict[str, float] = {}
        # Per-model detailed stats
        self._stats: Dict[str, ModelStats] = {mk: ModelStats() for mk in _MODELS_REGISTRY}
        # Sliding window of request timestamps for rate-limit estimation
        self._request_timestamps: List[float] = []
        # Daily request count + timestamp of last reset
        self._daily_request_count: int = 0
        self._daily_reset_at: float = time.time()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def call(
        self,
        task: str,
        messages: List[Dict[str, str]],
        **overrides: Any,
    ) -> Optional[str]:
        profile = self._task_profiles.get(task)
        if not profile:
            raise ValueError(f"Unknown task '{task}'. Available: {list(self._task_profiles.keys())}")

        model_keys = profile["model_keys"]
        params = {**profile["default_params"], **overrides}

        # Filter available models (not in cooldown, have API key)
        available = self._available_models(model_keys)
        if not available:
            logger.error("All models for task '%s' are in cooldown or unconfigured", task)
            return None

        # Round-robin: sort by usage count (least-used first)
        available.sort(key=lambda mk: self._usage.get(f"{task}:{mk}", 0))

        last_error: Optional[Exception] = None
        for model_key in available:
            model_cfg = _MODELS_REGISTRY[model_key]
            api_key = os.environ.get(model_cfg["env_key"])
            if not api_key:
                continue

            # Estimate input size and chunk if needed
            total_chars = sum(len(m.get("content", "")) for m in messages)
            if total_chars > MAX_INPUT_CHARS and task in ("product_extraction",):
                chunked = self._call_chunked(task, messages, model_key, model_cfg, api_key, params)
                if chunked is not None:
                    return chunked
                continue

            self._record_request()
            try:
                self._usage[f"{task}:{model_key}"] += 1
                logger.info("Calling %s for task '%s' (usage=%d)", model_cfg["model"], task, self._usage[f"{task}:{model_key}"])
                resp = completion(
                    model=model_cfg["model"],
                    api_key=api_key,
                    messages=messages,
                    **params,
                )
                content = resp.choices[0].message.content
                self._record_success(model_key, resp)
                if content:
                    return content.strip()
                logger.warning("%s returned empty content", model_cfg["model"])
            except Exception as exc:
                last_error = exc
                self._record_error(model_key, exc)
                exc_str = str(exc).lower()
                if "rate_limit" in exc_str or "429" in exc_str or "too many requests" in exc_str:
                    cooldown_until = time.time() + COOLDOWN_SECONDS
                    self._cooldowns[model_key] = cooldown_until
                    logger.warning(
                        "%s rate-limited — cooling down for %ds",
                        model_cfg["model"], COOLDOWN_SECONDS,
                    )
                else:
                    logger.warning(
                        "%s failed for task '%s': %s — trying next model",
                        model_cfg["model"], task, exc,
                    )
                continue

        logger.error("All models exhausted for task '%s'. Last error: %s", task, last_error)
        return None

    # ------------------------------------------------------------------
    # Chunked calling (for large inputs like product_extraction)
    # ------------------------------------------------------------------

    def _call_chunked(
        self,
        task: str,
        messages: List[Dict[str, str]],
        model_key: str,
        model_cfg: ModelConfig,
        api_key: str,
        params: Dict[str, Any],
    ) -> Optional[str]:
        """
        Split the last user message into chunks, call the model on each,
        and merge the JSON arrays into one response.
        """
        # Find the last user message (the one with all the page content)
        user_idx = -1
        for i in range(len(messages) - 1, -1, -1):
            if messages[i]["role"] == "user":
                user_idx = i
                break

        if user_idx < 0:
            return None

        full_text = messages[user_idx]["content"]
        # Split on page boundaries ("--- Page X ---" or similar markers)
        chunks = self._split_content(full_text)

        if len(chunks) <= 1:
            # Not enough to chunk — try normal call
            return self._call_single(task, messages, model_key, model_cfg, api_key, params)

        merged_results: List[str] = []
        self._usage[f"{task}:{model_key}"] += 1
        logger.info("Chunking %s for task '%s' into %d part(s)", model_cfg["model"], task, len(chunks))

        for idx, chunk in enumerate(chunks):
            chunk_messages = list(messages)
            chunk_messages[user_idx] = {"role": "user", "content": chunk}

            self._record_request()
            try:
                logger.info("Chunk %d/%d — calling %s", idx + 1, len(chunks), model_cfg["model"])
                resp = completion(
                    model=model_cfg["model"],
                    api_key=api_key,
                    messages=chunk_messages,
                    **params,
                )
                content = resp.choices[0].message.content
                self._record_success(model_key, resp)
                if content:
                    merged_results.append(content.strip())
                else:
                    logger.warning("Chunk %d returned empty content", idx + 1)
            except Exception as exc:
                self._record_error(model_key, exc)
                exc_str = str(exc).lower()
                if "rate_limit" in exc_str or "429" in exc_str:
                    self._cooldowns[model_key] = time.time() + COOLDOWN_SECONDS
                    logger.warning("Chunk %d hit rate limit on %s — cooling down", idx + 1, model_cfg["model"])
                else:
                    logger.warning("Chunk %d failed on %s: %s", idx + 1, model_cfg["model"], exc)

        if not merged_results:
            return None

        # Merge JSON arrays: extract [...], [...] -> [...]
        return self._merge_json_arrays(merged_results)

    def _call_single(
        self,
        task: str,
        messages: List[Dict[str, str]],
        model_key: str,
        model_cfg: ModelConfig,
        api_key: str,
        params: Dict[str, Any],
    ) -> Optional[str]:
        """Single call without chunking."""
        self._record_request()
        try:
            resp = completion(
                model=model_cfg["model"],
                api_key=api_key,
                messages=messages,
                **params,
            )
            content = resp.choices[0].message.content
            self._record_success(model_key, resp)
            if content:
                return content.strip()
        except Exception as exc:
            self._record_error(model_key, exc)
            exc_str = str(exc).lower()
            if "rate_limit" in exc_str or "429" in exc_str:
                self._cooldowns[model_key] = time.time() + COOLDOWN_SECONDS
            logger.warning("_call_single failed on %s: %s", model_cfg["model"], exc)
        return None

    # ------------------------------------------------------------------
    # Token / rate-limit tracking
    # ------------------------------------------------------------------

    def _record_request(self) -> None:
        now = time.time()
        self._request_timestamps.append(now)
        # Prune old entries (> 1 min)
        cutoff = now - RATE_LIMIT_WINDOW_SECONDS
        self._request_timestamps = [t for t in self._request_timestamps if t >= cutoff]

        # Daily counter: reset if 24h have passed
        if now - self._daily_reset_at > RATE_LIMIT_WINDOW_DAILY:
            self._daily_request_count = 0
            self._daily_reset_at = now
        self._daily_request_count += 1

    def _record_success(self, model_key: str, resp: Any) -> None:
        stats = self._stats[model_key]
        stats.success_count += 1
        stats.last_call_at = time.time()
        try:
            usage = resp.usage
            if usage:
                pt = getattr(usage, "prompt_tokens", 0) or 0
                ct = getattr(usage, "completion_tokens", 0) or 0
                tt = getattr(usage, "total_tokens", 0) or (pt + ct)
                stats.prompt_tokens += pt
                stats.completion_tokens += ct
                stats.total_tokens += tt
        except Exception:
            pass

    def _record_error(self, model_key: str, exc: Exception) -> None:
        stats = self._stats[model_key]
        exc_str = str(exc).lower()
        if "rate_limit" in exc_str or "429" in exc_str or "too many requests" in exc_str:
            stats.rate_limit_count += 1
        else:
            stats.error_count += 1
        stats.last_error_at = time.time()
        stats.last_error_msg = str(exc)[:200]

    def get_status(self) -> Dict[str, Any]:
        now = time.time()
        self._record_request()  # prunes old entries

        per_model: Dict[str, Dict[str, Any]] = {}
        for mk, cfg in _MODELS_REGISTRY.items():
            s = self._stats[mk]
            cd = self._cooldowns.get(mk)
            per_model[mk] = {
                "model": cfg["model"],
                "api_key_configured": bool(os.environ.get(cfg["env_key"])),
                "success_count": s.success_count,
                "rate_limit_count": s.rate_limit_count,
                "error_count": s.error_count,
                "prompt_tokens": s.prompt_tokens,
                "completion_tokens": s.completion_tokens,
                "total_tokens": s.total_tokens,
                "last_call_at": s.last_call_at,
                "last_error_at": s.last_error_at,
                "last_error_msg": s.last_error_msg,
                "in_cooldown": cd is not None and now < cd,
                "cooldown_remaining_sec": round(cd - now, 1) if cd and now < cd else 0,
            }

        # Rate-limit estimation
        window_requests = len(self._request_timestamps)
        daily_requests = self._daily_request_count

        total_rl = sum(s.rate_limit_count for s in self._stats.values())
        globally_limited = total_rl > 0 or window_requests >= OPENROUTER_FREE_REQ_PER_MIN

        return {
            "timestamp": now,
            "global": {
                "requests_last_min": window_requests,
                "requests_last_day": daily_requests,
                "free_tier_limit_per_min": OPENROUTER_FREE_REQ_PER_MIN,
                "free_tier_limit_per_day": OPENROUTER_FREE_REQ_PER_DAY,
                "estimated_remaining_per_min": max(0, OPENROUTER_FREE_REQ_PER_MIN - window_requests),
                "estimated_remaining_per_day": max(0, OPENROUTER_FREE_REQ_PER_DAY - daily_requests),
                "globally_rate_limited": globally_limited,
            },
            "models": per_model,
            "tasks": dict(_TASK_MODELS),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _available_models(self, model_keys: List[str]) -> List[str]:
        """Return model keys that are not in cooldown and have their API key set."""
        now = time.time()
        available: List[str] = []
        for mk in model_keys:
            if mk in self._cooldowns and now < self._cooldowns[mk]:
                continue
            cfg = _MODELS_REGISTRY.get(mk)
            if not cfg:
                continue
            if not os.environ.get(cfg["env_key"]):
                continue
            available.append(mk)
        return available

    def _split_content(self, text: str) -> List[str]:
        """Split large content into chunks at page boundaries."""
        MAX_CHUNK_CHARS = 3000

        # Try splitting on "--- Page" markers (product_extraction template)
        parts = []
        current: List[str] = []
        current_len = 0

        for line in text.split("\n"):
            line_len = len(line) + 1
            if line.startswith("--- Page ") and current_len > MAX_CHUNK_CHARS:
                parts.append("\n".join(current))
                current = []
                current_len = 0
            current.append(line)
            current_len += line_len

        if current:
            parts.append("\n".join(current))

        # If splitting by pages didn't produce chunks, split by char count
        if len(parts) == 1 and len(text) > MAX_CHUNK_CHARS:
            parts = []
            i = 0
            while i < len(text):
                chunk_end = min(i + MAX_CHUNK_CHARS, len(text))
                # Try to break at a newline
                if chunk_end < len(text):
                    nl = text.rfind("\n", i, chunk_end)
                    if nl > i:
                        chunk_end = nl + 1
                parts.append(text[i:chunk_end])
                i = chunk_end

        return parts

    # ------------------------------------------------------------------
    # Legacy compat: expose _usage and _cooldowns for existing callers
    # ------------------------------------------------------------------

    @property
    def usage(self) -> Counter:
        return self._usage

    @property
    def cooldowns(self) -> Dict[str, float]:
        return self._cooldowns


    def _merge_json_arrays(self, json_strings: List[str]) -> str:
        """Merge multiple JSON arrays like [a,b,c] + [d,e] -> [a,b,c,d,e]."""
        items: List[str] = []
        for s in json_strings:
            s = s.strip()
            # Remove ```json fences
            if s.startswith("```"):
                s = s.split("\n", 1)[-1] if "\n" in s else s
                s = s.rsplit("```", 1)[0] if "```" in s else s
            s = s.strip()
            # Extract content inside [ ... ]
            if s.startswith("[") and s.endswith("]"):
                inner = s[1:-1].strip()
                if inner:
                    # Split top-level objects by "}," or "}\n{"
                    items.append(inner)
            elif s.startswith("{") or s.startswith("["):
                items.append(s.lstrip("[").rstrip("]"))
        merged = "[" + ",".join(items) + "]"
        return merged


# Module-level singleton — import this to read status from endpoints
gateway = LLMGateway()
