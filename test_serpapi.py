import asyncio
import os
from dotenv import load_dotenv
load_dotenv()
from backend.services.apify_service import ApifyService

svc = ApifyService()
print(f"SerpAPI key configured: {bool(svc.serpapi_key)}")
if not svc.serpapi_key:
    print("WARNING: SERPAPI_API_KEY not found!")
else:
    result = asyncio.run(svc.discover_products({
        "search_queries": ["wireless headphones under 2000"],
        "category": "electronics",
        "keywords": ["wireless", "headphones"]
    }))
    print(f"Got {len(result)} products")
    for p in result[:3]:
        print(f"  - {p['name']} | Rs {p['price']} | {p.get('source', 'N/A')}")
