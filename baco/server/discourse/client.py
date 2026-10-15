import os
from dotenv import load_dotenv

load_dotenv()
api_key = os.environ.get("DISCOURSE_API_KEY", "")
api_username = os.environ.get("DISCOURSE_API_USERNAME", "system")

from baco.server.db.ingesta import discourse_base_url


def base_url() -> str:
    """Retorna la URL base de Discourse resuelta en runtime."""
    return discourse_base_url()


def __getattr__(name: str) -> str:
    if name == "BASE":
        return base_url()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

headers = {
    "Api-Key": api_key,
    "Api-Username": api_username,
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
}

