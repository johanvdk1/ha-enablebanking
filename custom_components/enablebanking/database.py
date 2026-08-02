"""Database layer for Enable Banking integration."""
import logging
import sqlite3
from datetime import datetime, date
from typing import Optional

from .const import DB_PATH

_LOGGER = logging.getLogger(__name__)


def init_db() -> None:
    """Create database and tables if they don't exist."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                entry_reference TEXT NOT NULL,
                account_uid TEXT NOT NULL,
                iban TEXT,
                bank TEXT,
                amount REAL NOT NULL,
                currency TEXT,
                credit_debit_indicator TEXT,
                booking_date TEXT,
                creditor_name TEXT,
                debtor_name TEXT,
                remittance_information TEXT,
                PRIMARY KEY (entry_reference, account_uid)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS balances (
                account_uid TEXT PRIMARY KEY,
                iban TEXT,
                bank TEXT,
                amount REAL,
                currency TEXT,
                balance_type TEXT,
                last_updated TEXT
            )
        """)
        conn.commit()
    _LOGGER.debug("Database initialized at %s", DB_PATH)


def save_transactions(uid: str, iban: str, bank: str, transactions: list) -> int:
    """Save transactions to database, skip duplicates. Returns count of new records."""
    new_count = 0
    with sqlite3.connect(DB_PATH) as conn:
        for tx in transactions:
            entry_reference = tx.get("entry_reference")
            if not entry_reference:
                continue
            try:
                creditor = tx.get("creditor") or {}
                debtor = tx.get("debtor") or {}
                remittance = ", ".join(tx.get("remittance_information") or [])
                conn.execute("""
                    INSERT OR IGNORE INTO transactions (
                        entry_reference, account_uid, iban, bank,
                        amount, currency, credit_debit_indicator,
                        booking_date, creditor_name, debtor_name,
                        remittance_information
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    entry_reference,
                    uid,
                    iban,
                    bank,
                    float(tx["transaction_amount"]["amount"]),
                    tx["transaction_amount"].get("currency", "EUR"),
                    tx.get("credit_debit_indicator"),
                    tx.get("booking_date"),
                    creditor.get("name"),
                    debtor.get("name"),
                    remittance,
                ))
                if conn.execute("SELECT changes()").fetchone()[0] > 0:
                    new_count += 1
            except Exception as err:
                _LOGGER.error("Error saving transaction %s: %s", entry_reference, err)
        conn.commit()
    _LOGGER.debug("Saved %d new transactions for %s", new_count, iban)
    return new_count


def save_balance(uid: str, iban: str, bank: str, balances: list) -> None:
    """Save latest balance to database."""
    # Prefer ITAV (interim available), fall back to ITBD
    balance = None
    for b in balances:
        if b.get("balance_type") == "ITAV":
            balance = b
            break
    if not balance and balances:
        balance = balances[0]
    if not balance:
        return
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO balances (
                    account_uid, iban, bank, amount, currency, balance_type, last_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                uid,
                iban,
                bank,
                float(balance["balance_amount"]["amount"]),
                balance["balance_amount"].get("currency", "EUR"),
                balance.get("balance_type"),
                datetime.utcnow().isoformat(),
            ))
            conn.commit()
        _LOGGER.debug("Saved balance for %s: %s", iban, balance["balance_amount"]["amount"])
    except Exception as err:
        _LOGGER.error("Error saving balance for %s: %s", iban, err)


def get_balance(uid: str) -> Optional[float]:
    """Get latest balance for an account."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(
                "SELECT amount FROM balances WHERE account_uid = ?", (uid,)
            ).fetchone()
            return row[0] if row else None
    except Exception as err:
        _LOGGER.error("Error reading balance for %s: %s", uid, err)
        return None


# Whitelists. Only these values are ever interpolated into SQL; everything
# else is passed as a bound parameter. Keep SENSOR_SCHEMA in __init__.py in
# sync with both dicts so bad YAML fails at startup, not at read time.

AGGREGATES = {
    "sum": "SUM",
    "avg": "AVG",
    "min": "MIN",
    "max": "MAX",
    "count": "COUNT",
    "total": "TOTAL",      # like SUM, but returns 0.0 instead of NULL on empty
}

MATCH_FIELDS = {
    "creditor": "creditor_name",
    "debtor": "debtor_name",
    "remittance": "remittance_information",
    "currency": "currency",
    "reference": "entry_reference",
}

MATCH_MODES = ("contains", "equals", "starts_with", "ends_with")


def _cycle_year(anchor_month: int, anchor_day: int, today: date) -> int:
    """Year in which the current cycle started.

    Unused now that _resolve_period no longer parses MM-DD anchors itself
    (that logic moved into the YAML's own Jinja, rendered upstream in
    sensor.py). Left in place rather than deleted.
    """
    if (today.month, today.day) >= (anchor_month, anchor_day):
        return today.year
    return today.year - 1


def _resolve_period(period) -> tuple:
    """Return (date_from, date_to) as ISO date strings, or None.

    `period` is a mapping {"from": ..., "to": ...}. Values arrive here
    already resolved -- any Jinja in the YAML (e.g. "{{ now().strftime(...) }}")
    is rendered upstream, in the sensor, before this function is called.
    Absent, missing, or empty means no restriction on that side.
    """
    if not period:
        return None, None
    return period.get("from") or None, period.get("to") or None


def get_transaction_total(
    uid: str,
    period=None,
    direction: str = "",
    matches: list = None,
    aggregate: str = "sum",
) -> float:
    """Aggregate stored transactions for one account.

    Every filter is optional and an empty/absent value means "no restriction",
    so an unfiltered call returns the aggregate over all stored transactions
    for the account. Runs against SQLite only -- no API call, no rate limit.
    """
    try:
        agg = AGGREGATES.get(str(aggregate).lower())
        if not agg:
            _LOGGER.error("Unknown aggregate %r, falling back to SUM", aggregate)
            agg = "SUM"

        # COUNT(amount) equals COUNT(*) here because amount is NOT NULL, but
        # COUNT(*) says what is meant.
        column = "*" if agg == "COUNT" else "amount"

        clauses = ["account_uid = ?"]
        params = [uid]

        for m in (matches or []):
            field = MATCH_FIELDS.get(m.get("field"))
            value = m.get("value")
            if not field or not value:
                continue

            mode = m.get("mode", "contains")
            value = str(value).lower()

            if mode == "equals":
                clauses.append(f"LOWER(COALESCE({field},'')) = ?")
                params.append(value)
            else:
                pattern = {
                    "contains": f"%{value}%",
                    "starts_with": f"{value}%",
                    "ends_with": f"%{value}",
                }.get(mode)
                if pattern is None:
                    _LOGGER.error("Unknown match mode %r, skipping", mode)
                    continue
                clauses.append(f"LOWER(COALESCE({field},'')) LIKE ?")
                params.append(pattern)

        if direction:
            clauses.append("credit_debit_indicator = ?")
            params.append(direction)

        date_from, date_to = _resolve_period(period)

        # String comparison, correct only because booking_date is ISO-8601
        # (YYYY-MM-DD), which sorts lexicographically as it does
        # chronologically. A bank returning any other format breaks this
        # silently rather than loudly.
        if date_from:
            clauses.append("booking_date >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("booking_date <= ?")
            params.append(date_to)

        query = (
            f"SELECT COALESCE({agg}({column}), 0) FROM transactions "
            f"WHERE {' AND '.join(clauses)}"
        )

        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(query, params).fetchone()
            return round(row[0], 2) if row else 0.0
    except Exception as err:
        _LOGGER.error("Error querying transaction total: %s", err)
        return 0.0
