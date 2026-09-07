from dotenv import load_dotenv
import os
load_dotenv()
print(f"Key found: {bool(os.environ.get('SERPAPI_API_KEY'))}")
print(f"Prefix: {os.environ.get('SERPAPI_API_KEY', '')[:20]}...")
