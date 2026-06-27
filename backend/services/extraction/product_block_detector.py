import re
from typing import List

class ProductBlockDetector:
    @staticmethod
    async def detect_blocks(text: str) -> List[str]:
        if not text:
            return []

        # Split text into separate product blocks using header/indicator patterns
        # Support list item bullets (*, -) before markdown headers (e.g. "* ### ")
        split_pattern = re.compile(
            r'(?:^\s*(?:\*|-)?\s*###\s+)|'  # * ### Header or ### Header
            r'(?:^\s*(?:\*|-)?\s*##\s+)|'   # * ## Header or ## Header
            r'(?:^\s*Image\s+\d+:)|'        # Image 25: Name
            r'(?:^\s*---\s*$)',              # horizontal rule
            re.MULTILINE
        )
        
        matches = list(split_pattern.finditer(text))
        if not matches or len(matches) < 2:
            # Fallback to general price/buy indicators if headers aren't clear
            alt_pattern = re.compile(r'(?:Price, product page|Buy now)', re.IGNORECASE)
            matches = list(alt_pattern.finditer(text))
            
        if not matches or len(matches) < 2:
            # Treats entire page as a single product details block
            return [text]

        # Slice text by matching offsets
        blocks = []
        prev_idx = 0
        for match in matches:
            start_idx = match.start()
            if start_idx > prev_idx:
                block_content = text[prev_idx:start_idx].strip()
                if len(block_content) > 50:
                    blocks.append(block_content)
            prev_idx = start_idx
            
        last_block = text[prev_idx:].strip()
        if len(last_block) > 50:
            blocks.append(last_block)
            
        return blocks
