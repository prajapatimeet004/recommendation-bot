import os, asyncio, httpx
from dotenv import load_dotenv
load_dotenv()
key = os.environ["SERPAPI_API_KEY"]

async def test():
    params = {"engine": "google_shopping", "q": "wireless headphones under 2000", "api_key": key, "num": 5}
    async with httpx.AsyncClient(timeout=20.0, verify=False) as client:
        resp = await client.get("https://serpapi.com/search", params=params)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            items = resp.json().get("shopping_results", [])
            print(f"Results: {len(items)}")
            for r in items[:3]:
                print(f"  {r.get('title')} | {r.get('price')} | {r.get('source')}")
        else:
            print(resp.text[:300])

asyncio.run(test())
