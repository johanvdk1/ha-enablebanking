"""Enable Banking API client."""
import json
import logging
import time
from datetime import datetime, timedelta, timezone

import jwt
from aiohttp import ClientSession, ClientResponseError
from cryptography.hazmat.primitives import serialization

from .const import API_BASE, PRIVATE_KEY_PATH, SESSIONS_PATH

_LOGGER = logging.getLogger(__name__)


class EnableBankingAPI:
    """Handle all Enable Banking API calls."""

    def __init__(self, app_id: str):
        self._app_id = app_id

    def _get_private_key(self):
        with open(PRIVATE_KEY_PATH, "rb") as f:
            return serialization.load_pem_private_key(f.read(), password=None)

    def _get_sessions(self) -> dict:
        with open(SESSIONS_PATH) as f:
            return json.load(f)

    def _get_jwt(self):
        now = int(time.time())
        payload = {
            "iss": "enablebanking.com",
            "aud": "api.enablebanking.com",
            "iat": now,
            "exp": now + 3600,
        }
        return jwt.encode(
            payload,
            self._get_private_key(),
            algorithm="RS256",
            headers={"kid": self._app_id},
        )

    def _get_headers(self):
        return {"Authorization": f"Bearer {self._get_jwt()}"}

    def _get_accounts(self):
        sessions = self._get_sessions()
        accounts = []
        for bank_name, session in sessions.items():
            for account in session.get("accounts", []):
                accounts.append({
                    "uid": account.get("uid"),
                    "iban": account.get("account_id", {}).get("iban", account.get("uid")),
                    "name": account.get("name", ""),
                    "bank": bank_name,
                })
        return accounts

    async def fetch_transactions(self, session: ClientSession) -> dict:
        """Fetch transactions for all accounts."""
        result = {
            "accounts": {},
            "rate_limited": False,
        }
        for account in self._get_accounts():
            uid = account["uid"]
            iban = account["iban"]
            try:
                date_from = (datetime.now(timezone.utc) - timedelta(days=89)).strftime("%Y-%m-%d")
                date_to = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                async with session.get(
                    f"{API_BASE}/accounts/{uid}/transactions",
                    headers=self._get_headers(),
                    params={"date_from": date_from, "date_to": date_to},
                ) as r:
                    if r.status == 429:
                        _LOGGER.warning("Rate limit hit for transactions on %s", iban)
                        result["rate_limited"] = True
                        continue
                    r.raise_for_status()
                    data = await r.json()
                    result["accounts"][uid] = {
                        "bank": account["bank"],
                        "iban": iban,
                        "name": account["name"],
                        "transactions": data.get("transactions", []),
                    }
                    _LOGGER.debug("Fetched transactions for %s", iban)
            except ClientResponseError as err:
                _LOGGER.error("HTTP error fetching transactions for %s: %s", iban, err)
            except Exception as err:
                _LOGGER.error("Error fetching transactions for %s: %s", iban, err)
        return result

    async def fetch_balances(self, session: ClientSession) -> dict:
        """Fetch balances for all accounts."""
        result = {
            "accounts": {},
            "rate_limited": False,
        }
        for account in self._get_accounts():
            uid = account["uid"]
            iban = account["iban"]
            try:
                async with session.get(
                    f"{API_BASE}/accounts/{uid}/balances",
                    headers=self._get_headers(),
                ) as r:
                    if r.status == 429:
                        _LOGGER.warning("Rate limit hit for balances on %s", iban)
                        result["rate_limited"] = True
                        continue
                    r.raise_for_status()
                    data = await r.json()
                    result["accounts"][uid] = {
                        "bank": account["bank"],
                        "iban": iban,
                        "name": account["name"],
                        "balances": data.get("balances", []),
                    }
                    _LOGGER.debug("Fetched balances for %s", iban)
            except ClientResponseError as err:
                _LOGGER.error("HTTP error fetching balances for %s: %s", iban, err)
            except Exception as err:
                _LOGGER.error("Error fetching balances for %s: %s", iban, err)
        return result
