import re
import difflib
from typing import List, Dict

class SpellingService:
    def __init__(self) -> None:
        # Curated common typos in shopping
        self.typo_map = {
            "samsng": "samsung",
            "samsang": "samsung",
            "aple": "apple",
            "iphne": "iphone",
            "iphn": "iphone",
            "laptob": "laptop",
            "lapy": "laptop",
            "shos": "shoes",
            "shooes": "shoes",
            "sheos": "shoes",
            "sneekers": "sneakers",
            "snakers": "sneakers",
            "fashon": "fashion",
            "clothe": "clothes",
            "cloths": "clothes",
            "recomended": "recommended",
            "recommen": "recommend",
            "sugest": "suggest",
            "sugestions": "suggestions",
            "budjet": "budget",
            "heaphone": "headphones",
            "heaphones": "headphones",
            "earfone": "earphones",
            "earfones": "earphones",
            "womns": "womens",
            "menss": "mens",
            "smrtphone": "smartphone",
            "smrtwatch": "smartwatch",
            "hedphones": "headphones",
            "erphones": "earphones",
            "gim": "gym",
            "t-shrt": "t-shirt",
            "tshrt": "t-shirt",
            "jean": "jeans",
            "trouser": "trousers",
            "sare": "saree",
            "sari": "saree",
            "kurti": "kurta",
            "jaket": "jacket",
            "hody": "hoodie",
            "hodi": "hoodie",
            "fresness": "freshness",
            "availablity": "availability",
            "discunt": "discount",
            "electonics": "electronics",
            "electonic": "electronics",
            "gadjet": "gadget",
            "gadjets": "gadgets",
            "camra": "camera",
            "tablt": "tablet",
            "macbk": "macbook",
            "nik": "nike",
            "adida": "adidas",
            "adilas": "adidas",
            "rebook": "reebok",
            "undr": "under",
            "belw": "below",
            "abve": "above",
        }

        # Curated vocabulary for fuzzy close matches
        self.vocabulary = [
            # Categories
            "smartphones", "laptops", "fashion", "beauty", "footwear", "home_appliances", "electronics",
            # Common Brands
            "samsung", "apple", "xiaomi", "redmi", "oneplus", "oppo", "vivo", "realme", "nothing",
            "motorola", "poco", "lenovo", "asus", "dell", "hp", "acer", "sony", "nike", "adidas",
            "puma", "reebok", "boat", "noise", "fireboltt", "fastrack", "casio", "titan", "levis",
            "zara", "roadster", "hrx", "wrogn",
            # Product types
            "phone", "mobile", "smartphone", "iphone", "laptop", "notebook", "macbook", "computer",
            "tablet", "ipad", "shirt", "tshirt", "t-shirt", "jeans", "trousers", "pants", "dress",
            "kurta", "saree", "jacket", "hoodie", "shoes", "sneakers", "sandals", "slippers",
            "heels", "boots", "watch", "smartwatch", "headphones", "earphones", "earbuds",
            "speaker", "soundbar", "television", "tv", "refrigerator", "fridge", "washing",
            "machine", "air", "conditioner", "microwave", "oven", "sunscreen", "moisturizer",
            "lipstick", "makeup", "foundation", "shampoo", "conditioner", "cream", "perfume",
            "serum", "skincare", "soap", "lotion", "oil", "deodorant", "accessories", "gadget",
            # E-commerce actions & constraints
            "under", "below", "above", "within", "budget", "price", "cost", "cheap", "premium",
            "expensive", "discount", "offer", "sale", "deal", "buy", "find", "suggest",
            "recommend", "compare", "versus", "difference", "details", "specs", "specifications",
            "review", "rating", "brand", "color", "size", "gender", "men", "women", "unisex",
            "combo", "kit", "set", "bundle"
        ]

    def correct_word(self, word: str) -> str:
        # If it is empty or a number, leave it
        if not word or word.isdigit():
            return word

        # Strip punctuation from start/end to get clean check word
        match = re.match(r"^([^\w]*)(.*?)([^\w]*)$", word)
        if not match:
            return word
        prefix, clean_word, suffix = match.groups()

        if not clean_word:
            return word

        clean_lower = clean_word.lower()

        # 1. Check exact map (including short terms mapped explicitly)
        if clean_lower in self.typo_map:
            corrected = self.typo_map[clean_lower]
            return prefix + self._match_case(clean_word, corrected) + suffix

        # If the word is very short, skip fuzzy matching to avoid false positives
        if len(clean_lower) <= 3:
            return word

        # 2. Check exact vocabulary match
        if clean_lower in self.vocabulary:
            return word

        # 3. Check fuzzy close matches
        matches = difflib.get_close_matches(clean_lower, self.vocabulary, n=1, cutoff=0.78)
        if matches:
            corrected = matches[0]
            # Don't correct if it's too different (length difference too high)
            if abs(len(clean_lower) - len(corrected)) <= 2:
                return prefix + self._match_case(clean_word, corrected) + suffix

        return word

    def _match_case(self, original: str, corrected: str) -> str:
        """Helper to match the casing of the original word."""
        if original.isupper():
            return corrected.upper()
        if original.istitle():
            return corrected.capitalize()
        return corrected

    def correct_query(self, query: str) -> str:
        if not query:
            return query
        
        # Split by spaces preserving whitespaces
        tokens = re.split(r"(\s+)", query)
        corrected_tokens = []
        for token in tokens:
            if not token.strip():
                corrected_tokens.append(token)
            else:
                corrected_tokens.append(self.correct_word(token))
                
        return "".join(corrected_tokens)
