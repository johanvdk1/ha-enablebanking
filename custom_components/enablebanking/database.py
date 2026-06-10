"""Database layer for Enable Banking integration."""
import logging
import sqlite3
from datetime import datetime
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


def get_transaction_total(
    uid: str,
    creditor_filter: str = "",
    period: str = "year",
    direction: str = "DBIT",
) -> float:
    """Query transaction total from database."""
    try:
        now = datetime.now()
        if period == "year":
            date_from = f"{now.year}-01-01"
        elif period == "month":
            date_from = f"{now.year}-{now.month:02d}-01"
        else:
            date_from = None

        query = """
            SELECT COALESCE(SUM(amount), 0)
            FROM transactions
            WHERE account_uid = ?
            AND credit_debit_indicator = ?
        """
        params = [uid, direction]

        if date_from:
            query += " AND booking_date >= ?"
            params.append(date_from)

        if creditor_filter:
            query += " AND LOWER(creditor_name) LIKE ?"
            params.append(f"%{creditor_filter.lower()}%")

        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(query, params).fetchone()
            return round(row[0], 2) if row else 0.0
    except Exception as err:
        _LOGGER.error("Error querying transaction total: %s", err)
        return 0.0
