"""
Enable Banking — bank account authorisation script.

Run this script once per bank account to obtain a session that the
Home Assistant integration can use to fetch balances and transactions.
The resulting session is appended to (or creates) sessions.json.

Usage
-----
1.  Edit the CONFIG block below.
2.  python3 auth_bank.py
3.  Open the printed URL in your browser and log in to your bank.
4.  You will be redirected to https://localhost/local?code=...
    The browser will show an error — that is expected.
5.  Copy the full URL from the address bar and paste it at the prompt.
6.  The script saves the session to SESSIONS_PATH.
7.  Copy sessions.json to /config/enablebanking/sessions.json on HA:
        ssh hassio@YOUR_HA_IP "cat > /homeassistant/enablebanking/sessions.json" < sessions.json
"""

import json
import time
import requests
from datetime import datetime, timedelta, timezone
from cryptography.hazmat.primitives import serialization
import jwt

# ---------------------------------------------------------------------------
# CONFIG — edit these values
# ---------------------------------------------------------------------------
APP_ID          = "YOUR_APP_ID"
PRIVATE_KEY_PATH = "private.key"          # relative to this script, or absolute
SESSIONS_PATH   = "sessions.json"         # where sessions are saved/loaded
REDIRECT_URL    = "https://localhost/local"
API_BASE        = "https://api.enablebanking.com"

BANK_NAME       = "Argenta"               # change for each bank
BANK_COUNTRY    = "BE"
# ---------------------------------------------------------------------------


def _load_key():
    with open(PRIVATE_KEY_PATH, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def _get_jwt():
    now = int(time.time())
    return jwt.encode(
        {
            "iss": "enablebanking.com",
            "aud": "api.enablebanking.com",
            "iat": now,
            "exp": now + 3600,
        },
        _load_key(),
        algorithm="RS256",
        headers={"kid": APP_ID},
    )


def _headers():
    return {"Authorization": f"Bearer {_get_jwt()}"}


def _find_bank():
    r = requests.get(
        f"{API_BASE}/aspsps",
        headers=_headers(),
        params={"country": BANK_COUNTRY},
    )
    r.raise_for_status()
    for aspsp in r.json().get("aspsps", []):
        if BANK_NAME.lower() in aspsp["name"].lower():
            return aspsp
    return None


def authorise():
    print(f"Looking up {BANK_NAME} ({BANK_COUNTRY})…")
    bank = _find_bank()
    if not bank:
        print(f"Bank '{BANK_NAME}' not found. Check BANK_NAME and BANK_COUNTRY.")
        return

    print(f"Found: {bank['name']}")

    valid_until = (
        datetime.now(timezone.utc) + timedelta(days=90)
    ).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    r = requests.post(
        f"{API_BASE}/auth",
        headers=_headers(),
        json={
            "access": {
                "balances": True,
                "transactions": True,
                "valid_until": valid_until,
            },
            "aspsp": {"name": bank["name"], "country": bank["country"]},
            "state": "homeassistant",
            "redirect_url": REDIRECT_URL,
            "psu_type": "personal",
        },
    )
    r.raise_for_status()
    data = r.json()

    print(f"\nOpen this URL in your browser:\n\n  {data['url']}\n")
    print(
        "After logging in you will be redirected to https://localhost/local?code=…\n"
        "The browser will show an error — that is expected.\n"
        "Copy the FULL URL from the address bar and paste it here:"
    )
    redirect = input("> ").strip()

    # Extract code from redirect URL
    try:
        code = redirect.split("code=")[1].split("&")[0]
    except IndexError:
        print("Could not find 'code' in the URL. Please try again.")
        return

    r = requests.post(
        f"{API_BASE}/sessions",
        headers=_headers(),
        json={"code": code},
    )
    r.raise_for_status()
    session = r.json()

    print(f"\nSession created successfully!")
    print(f"Session ID : {session.get('session_id')}")
    print("Accounts   :")
    for acc in session.get("accounts", []):
        iban = acc.get("account_id", {}).get("iban", "—")
        name = acc.get("name", "")
        print(f"  {iban}  {name}")

    # Load existing sessions (if any) and add/replace this bank
    sessions = {}
    try:
        with open(SESSIONS_PATH) as f:
            sessions = json.load(f)
    except FileNotFoundError:
        pass

    sessions[BANK_NAME] = session

    with open(SESSIONS_PATH, "w") as f:
        json.dump(sessions, f, indent=2)

    print(f"\nSaved to {SESSIONS_PATH}")
    print(
        "\nNext step — copy to Home Assistant:\n"
        f"  ssh hassio@YOUR_HA_IP "
        f'"cat > /homeassistant/enablebanking/sessions.json" '
        f"< {SESSIONS_PATH}"
    )


if __name__ == "__main__":
    authorise()
