import httpx, os
from dotenv import load_dotenv

load_dotenv()
api_key = os.environ.get("DISCOURSE_API_KEY", "")
api_username = os.environ.get("DISCOURSE_API_USERNAME", "system")

BASE = "https://bc-dev.finneg.com"
headers = {
    "Api-Key": api_key,
    "Api-Username": api_username,
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
}

