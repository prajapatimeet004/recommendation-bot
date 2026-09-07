import os
os.environ["SERPAPI_API_KEY"] = "b0ffff3c2299551401bdfcf35ea9be8283c0aab612cc0241c5d813e4f0f2a393"
print(f"Key set: {bool(os.environ.get('SERPAPI_API_KEY'))}")
from backend.services.apify_service import ApifyService
svc = ApifyService()
print(f"SerpAPI key configured: {bool(svc.serpapi_key)}")
import asyncio
result = asyncio.run(svc.discover_products({
    "search_queries": ["wireless headphones under 2000"],
    "category": "electronics",
    "keywords": ["wireless", "headphones"]
}))
print(f"Got {len(result)} products")
for p in result[:3]:
    print(f"  - {p['name']} | Rs {p['price']} | {p.get('source', 'N/A')}")
