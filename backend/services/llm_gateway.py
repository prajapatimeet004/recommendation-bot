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
# Model registry
# ---------------------------------------------------------------------------

class ModelConfig(TypedDict):
    model: str
    env_key: str


_MODELS_REGISTRY: Dict[str, ModelConfig] = {
    "gpt-oss-120b": {"model": "openrouter/openai/gpt-oss-120b:free", "env_key": "OPENROUTER_API_KEY"},
    "gpt-oss-20b": {"model": "openrouter/openai/gpt-oss-20b:free", "env_key": "OPENROUTER_API_KEY"},
    "nemotron-3-nano-30b": {"model": "openrouter/nvidia/nemotron-3-nano-30b-a3b:free", "env_key": "OPENROUTER_API_KEY"},
    "qwen3-next-80b-a3b": {"model": "openrouter/qwen/qwen3-next-80b-a3b-instruct:free", "env_key": "OPENROUTER_API_KEY"},
    "llama-3.3-70b": {"model": "openrouter/meta-llama/llama-3.3-70b-instruct:free", "env_key": "OPENROUTER_API_KEY"},
    "nemotron-3-ultra-550b": {"model": "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free", "env_key": "OPENROUTER_API_KEY"},
}


# ---------------------------------------------------------------------------
# Task → model assignments (spread load across models)
# ---------------------------------------------------------------------------

_TASK_MODELS: Dict[str, List[str]] = {
    "intent_classification": ["llama-3.3-70b", "gpt-oss-20b", "nemotron-3-nano-30b"],
    "context_keyword_generation": ["llama-3.3-70b", "gpt-oss-20b", "nemotron-3-nano-30b"],
    "product_extraction": ["gpt-oss-120b", "qwen3-next-80b-a3b", "nemotron-3-ultra-550b"],
    "response_generation": ["gpt-oss-120b", "qwen3-next-80b-a3b", "llama-3.3-70b"],
    "comparison": ["gpt-oss-120b", "llama-3.3-70b", "qwen3-next-80b-a3b"],
    "summarization": ["gpt-oss-20b", "nemotron-3-nano-30b", "llama-3.3-70b"],
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


class LLMGateway:
    def __init__(self) -> None:
        self._task_profiles = _TASK_PROFILES
        # Round-robin: per-task count per model key
        self._usage: Counter = Counter()
        # Cooldown: model_key -> timestamp until which it's skipped
        self._cooldowns: Dict[str, float] = {}

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
                if content:
                    return content.strip()
                logger.warning("%s returned empty content", model_cfg["model"])
            except Exception as exc:
                last_error = exc
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

            try:
                logger.info("Chunk %d/%d — calling %s", idx + 1, len(chunks), model_cfg["model"])
                resp = completion(
                    model=model_cfg["model"],
                    api_key=api_key,
                    messages=chunk_messages,
                    **params,
                )
                content = resp.choices[0].message.content
                if content:
                    merged_results.append(content.strip())
                else:
                    logger.warning("Chunk %d returned empty content", idx + 1)
            except Exception as exc:
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
        try:
            resp = completion(
                model=model_cfg["model"],
                api_key=api_key,
                messages=messages,
                **params,
            )
            content = resp.choices[0].message.content
            if content:
                return content.strip()
        except Exception as exc:
            exc_str = str(exc).lower()
            if "rate_limit" in exc_str or "429" in exc_str:
                self._cooldowns[model_key] = time.time() + COOLDOWN_SECONDS
            logger.warning("_call_single failed on %s: %s", model_cfg["model"], exc)
        return None

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
