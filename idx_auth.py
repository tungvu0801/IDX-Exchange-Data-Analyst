"""
IDX Exchange token request, shared by the fetch scripts and the batch downloader.

The token-proxy key is read from the IDX_TOKEN_KEY environment variable, or from
a local .env file in this folder (git-ignored - never commit it). Error messages
never include the key or the token.
"""

import os
from pathlib import Path

import requests

ENV_FILE = Path(__file__).resolve().parent / ".env"
TOKEN_ENDPOINT = "https://idxexchange.com/internal-api/trestle_token.php"


class AuthError(Exception):
    """Authentication failed. The message is safe to print (contains no secrets)."""


def load_token_key():
    key = os.environ.get("IDX_TOKEN_KEY", "").strip()
    if not key and ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip() == "IDX_TOKEN_KEY":
                key = value.strip().strip("\"'")
    if not key:
        raise AuthError(
            f"IDX_TOKEN_KEY is not set. Add the line IDX_TOKEN_KEY=<your key> to {ENV_FILE} "
            f"(git-ignored), or set it as an environment variable."
        )
    return key


def get_token(timeout=30):
    """Ask the IDX Exchange proxy for a Trestle access token."""
    key = load_token_key()
    try:
        response = requests.get(TOKEN_ENDPOINT, params={"key": key}, timeout=timeout)
    except requests.RequestException as err:
        # requests' own messages contain the full URL, key included, so report only the error type
        raise AuthError(
            f"Could not reach the IDX Exchange token service ({type(err).__name__}). "
            f"Check your internet connection and try again."
        ) from None

    if response.status_code != 200:
        detail = response.text[:200].replace(key, "***").strip()
        raise AuthError(
            f"The IDX Exchange token service answered HTTP {response.status_code}"
            f"{f' ({detail})' if detail else ''}. The key in IDX_TOKEN_KEY may be wrong or "
            f"expired - ask your IDX Exchange contact for a valid one."
        )
    try:
        data = response.json()
    except ValueError:
        data = None
    token = data.get("access_token") if isinstance(data, dict) else None
    if not token:
        raise AuthError(
            "The IDX Exchange token service replied without an access_token. "
            "The key may be wrong, or the service may be down."
        )
    return token
