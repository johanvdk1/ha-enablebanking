"""Enable Banking API client."""
import logging
import time
from datetime import datetime, timedelta, timezone

import jwt
import requests
from cryptography.hazmat.primitives import serialization

from .const import API_BASE

_LOGGER = logging.getLogger(__name__)


class EnableBankingAPI:
    """Handle all Enable Banking API calls."""

    def __init__(self, app_id: str, private_key: str, sessions: dict):
        self._app_id = app_id
        self._private_key_pem = private_key
        self._sessions = sessions

    def _get_private_key(self):
        return serialization.load_pem_private_key(
            self._private_key_pem.encode(), password=None
        )

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

    def _get_transactions(self, uid: str) -> list:
        date_from = (datetime.now(timezone.utc) - timedelta(days=89)).strftime("%Y-%m-%d")
        date_to = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        r = requests.get(
            f"{API_BASE}/accounts/{uid}/transactions",
            headers=self._get_headers(),
            params={"date_from": date_from, "date_to": date_to},
            timeout=30,
        )
        r.raise_for_status()
        return r.json().get("transactions", [])

    def _get_balances(self, uid: str) -> list:
        r = requests.get(
            f"{API_BASE}/accounts/{uid}/balances",
            headers=self._get_headers(),
            timeout=30,
        )
        r.raise_for_status()
        return r.json().get("balances", [])

    def fetch_all(self) -> dict:
        """Fetch balances and transactions for all accounts."""
        result = {}
        for bank_name, session in self._sessions.items():
            for account in session.get("accounts", []):
                uid = account.get("uid")
                iban = account.get("account_id", {}).get("iban", uid)
                account_name = account.get("name", iban)
                try:
                    balances = self._get_balances(uid)
                    transactions = self._get_transactions(uid)
                    result[uid] = {
                        "bank": bank_name,
                        "iban": iban,
                        "name": account_name,
                        "balances": balances,
                        "transactions": transactions,
                    }
                    _LOGGER.debug("Fetched data for %s (%s)", account_name, iban)
                except Exception as err:
                    _LOGGER.error("Error fetching data for %s: %s", iban, err)
        return result
