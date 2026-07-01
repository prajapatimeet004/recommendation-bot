import logging
import numpy as np
from typing import Dict, Any, List, Optional
from backend.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)

# Few-shot examples for intent and category matching
CLASSIFIER_EXAMPLES = [
    # GREETINGS / COURTESY
    {"text": "hello", "intent": "GREETING", "category": "other"},
    {"text": "hi there", "intent": "GREETING", "category": "other"},
    {"text": "hey, how are you?", "intent": "GREETING", "category": "other"},
    {"text": "thank you so much", "intent": "GREETING", "category": "other"},
    {"text": "thanks for the help", "intent": "GREETING", "category": "other"},
    {"text": "bye, see you later", "intent": "GREETING", "category": "other"},
    {"text": "good morning", "intent": "GREETING", "category": "other"},
    {"text": "hi assistant", "intent": "GREETING", "category": "other"},

    # GENERAL INFO / OFF-TOPIC / NON-SHOPPING
    {"text": "what is the weather today?", "intent": "GENERAL", "category": "other"},
    {"text": "who is the prime minister of India?", "intent": "GENERAL", "category": "other"},
    {"text": "tell me a joke", "intent": "GENERAL", "category": "other"},
    {"text": "sing a song for me", "intent": "GENERAL", "category": "other"},
    {"text": "write a python function to sort a list", "intent": "GENERAL", "category": "other"},
    {"text": "tell me about black holes", "intent": "GENERAL", "category": "other"},

    # RECOMMEND - smartphones
    {"text": "recommend me a good smartphone", "intent": "RECOMMEND", "category": "smartphones"},
    {"text": "best mobile phone under 20000 rs", "intent": "RECOMMEND", "category": "smartphones"},
    {"text": "looking for a 5g phone with high battery backup", "intent": "RECOMMEND", "category": "smartphones"},
    {"text": "suggest iphone with good camera specs", "intent": "RECOMMEND", "category": "smartphones"},
    {"text": "samsung galaxy mobile around 30k", "intent": "RECOMMEND", "category": "smartphones"},
    
    # RECOMMEND - laptops
    {"text": "i want to buy a new laptop for programming and office work", "intent": "RECOMMEND", "category": "laptops"},
    {"text": "best gaming laptop under 80k in India", "intent": "RECOMMEND", "category": "laptops"},
    {"text": "thin and light notebook for college students", "intent": "RECOMMEND", "category": "laptops"},
    {"text": "macbook or windows laptop for video editing", "intent": "RECOMMEND", "category": "laptops"},
    
    # RECOMMEND - fashion
    {"text": "suggest some casual t-shirts for men", "intent": "RECOMMEND", "category": "fashion"},
    {"text": "need clothes for a wedding ceremony", "intent": "RECOMMEND", "category": "fashion"},
    {"text": "traditional wear or kurta for navratri festival", "intent": "RECOMMEND", "category": "fashion"},
    {"text": "women oversized hoodie and sweatpants", "intent": "RECOMMEND", "category": "fashion"},
    {"text": "summer dresses and cotton shirts online", "intent": "RECOMMEND", "category": "fashion"},
    
    # RECOMMEND - beauty
    {"text": "best sunscreen SPF 50 for dry skin", "intent": "RECOMMEND", "category": "beauty"},
    {"text": "moisturizer and face serum for glowing skin", "intent": "RECOMMEND", "category": "beauty"},
    {"text": "lipstick shades for daily office wear", "intent": "RECOMMEND", "category": "beauty"},
    {"text": "skincare products for acne prone skin", "intent": "RECOMMEND", "category": "beauty"},
    {"text": "anti hair fall shampoo and conditioner", "intent": "RECOMMEND", "category": "beauty"},
    
    # RECOMMEND - footwear
    {"text": "running shoes for marathon training", "intent": "RECOMMEND", "category": "footwear"},
    {"text": "sneakers for daily wear under 3000", "intent": "RECOMMEND", "category": "footwear"},
    {"text": "leather boots for winter", "intent": "RECOMMEND", "category": "footwear"},
    {"text": "sandals and slippers for beach vacation", "intent": "RECOMMEND", "category": "footwear"},
    {"text": "heels and formal shoes for women", "intent": "RECOMMEND", "category": "footwear"},
    
    # RECOMMEND - home_appliances
    {"text": "double door refrigerator with good rating", "intent": "RECOMMEND", "category": "home_appliances"},
    {"text": "front load washing machine for home", "intent": "RECOMMEND", "category": "home_appliances"},
    {"text": "1.5 ton split AC for hot summer", "intent": "RECOMMEND", "category": "home_appliances"},
    {"text": "smart TV 55 inch 4K display", "intent": "RECOMMEND", "category": "home_appliances"},
    {"text": "microwave oven for baking and grilling", "intent": "RECOMMEND", "category": "home_appliances"},
    
    # RECOMMEND - electronics
    {"text": "best noise cancelling headphones", "intent": "RECOMMEND", "category": "electronics"},
    {"text": "smartwatch under 5000 with call feature", "intent": "RECOMMEND", "category": "electronics"},
    {"text": "bluetooth speaker with deep bass", "intent": "RECOMMEND", "category": "electronics"},
    {"text": "ipad or drawing tablet for digital art", "intent": "RECOMMEND", "category": "electronics"},
    {"text": "wireless mouse and mechanical keyboard combo", "intent": "RECOMMEND", "category": "electronics"},

    # COMPARE
    {"text": "compare iphone 15 and samsung s24", "intent": "COMPARE", "category": "smartphones"},
    {"text": "difference between oled and qled tv", "intent": "COMPARE", "category": "home_appliances"},
    {"text": "macbook air vs dell xps comparison", "intent": "COMPARE", "category": "laptops"},
    {"text": "asus rog vs hp victus which is better", "intent": "COMPARE", "category": "laptops"},
    {"text": "should I buy nike pegasus or adidas ultraboost", "intent": "COMPARE", "category": "footwear"},
    {"text": "compare these two products", "intent": "COMPARE", "category": "other"},
    {"text": "which is better between samsung and apple", "intent": "COMPARE", "category": "smartphones"},

    # FOLLOW_UP
    {"text": "show me more options", "intent": "FOLLOW_UP", "category": "other"},
    {"text": "do you have any cheaper alternatives?", "intent": "FOLLOW_UP", "category": "other"},
    {"text": "what other colors are available in this dress?", "intent": "FOLLOW_UP", "category": "fashion"},
    {"text": "show me similar shoes but in blue color", "intent": "FOLLOW_UP", "category": "footwear"},
    {"text": "do you have accessories for that tablet?", "intent": "FOLLOW_UP", "category": "electronics"},
    {"text": "any discounts or cheaper options for this model?", "intent": "FOLLOW_UP", "category": "other"},
    {"text": "show me more like this", "intent": "FOLLOW_UP", "category": "other"},

    # BUNDLE
    {"text": "gym kit or workout setup for beginners", "intent": "BUNDLE", "category": "other"},
    {"text": "gaming setup accessories combo", "intent": "BUNDLE", "category": "electronics"},
    {"text": "cricket kit for kids with bat, ball, and pads", "intent": "BUNDLE", "category": "other"},
    {"text": "skincare routine bundle for oily skin", "intent": "BUNDLE", "category": "beauty"},
    {"text": "new office desk setup essentials package", "intent": "BUNDLE", "category": "other"},
    {"text": "everything i need to start boxing", "intent": "BUNDLE", "category": "other"},

    # EXPLAIN
    {"text": "what is refresh rate and how does it work?", "intent": "EXPLAIN", "category": "electronics"},
    {"text": "tell me about display technology like AMOLED and IPS", "intent": "EXPLAIN", "category": "electronics"},
    {"text": "what specs should I look for in a gaming laptop?", "intent": "EXPLAIN", "category": "laptops"},
    {"text": "explain the difference between active noise cancellation and passive noise isolation", "intent": "EXPLAIN", "category": "electronics"},
    {"text": "explain the features of this smartphone", "intent": "EXPLAIN", "category": "smartphones"},
]


class LocalIntentClassifier:
    _instance: Optional['LocalIntentClassifier'] = None

    @classmethod
    def instance(cls) -> 'LocalIntentClassifier':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._embed_service = EmbeddingService()
        self._initialized = False
        self._example_embeddings: Optional[np.ndarray] = None
        self._examples = CLASSIFIER_EXAMPLES

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        
        logger.info("Initializing LocalIntentClassifier embeddings for %d examples...", len(self._examples))
        texts = [ex["text"] for ex in self._examples]
        # Generate batch embeddings
        embeddings_list = self._embed_service.generate_batch(texts)
        self._example_embeddings = np.array(embeddings_list, dtype=np.float32)
        
        # L2 normalize them for fast cosine similarity via dot product
        norms = np.linalg.norm(self._example_embeddings, axis=1, keepdims=True)
        # Avoid division by zero just in case
        norms = np.where(norms == 0, 1.0, norms)
        self._example_embeddings = self._example_embeddings / norms
        
        self._initialized = True
        logger.info("LocalIntentClassifier embeddings successfully initialized.")

    def classify(self, query: str) -> Optional[Dict[str, str]]:
        """
        Classifies user query into an intent and category using semantic cosine similarity.
        Returns a dict with 'intent' and 'category' keys, or None if classification fails.
        """
        if not query or not query.strip():
            return None

        try:
            self._ensure_initialized()
            
            # Embed the query
            query_embedding = np.array(self._embed_service.generate(query), dtype=np.float32)
            norm = np.linalg.norm(query_embedding)
            if norm > 0:
                query_embedding = query_embedding / norm
            
            # Compute cosine similarities (dot product since both are normalized)
            similarities = np.dot(self._example_embeddings, query_embedding)
            
            # Find the best match
            best_idx = int(np.argmax(similarities))
            best_similarity = float(similarities[best_idx])
            best_match = self._examples[best_idx]
            
            logger.info("LocalIntentClassifier matched query '%s' to example '%s' with similarity %.4f", 
                        query, best_match["text"], best_similarity)
            
            # We can have a small threshold, e.g. if similarity is extremely low, but for general inputs
            # a nearest neighbor matches well.
            return {
                "intent": best_match["intent"],
                "category": best_match["category"]
            }
        except Exception as e:
            logger.error("Error running LocalIntentClassifier.classify: %s", e, exc_info=True)
            return None
