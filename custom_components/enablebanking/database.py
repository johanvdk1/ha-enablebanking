"""Database layer for Enable Banking integration."""
import logging
import sqlite3
from datetime import datetime, date
from typing import Optional

from .const import DB_PATH

_LOGGER = logging.getLogger(__name__)


def init_db() -> None:
    """Create database and tables if they don't exist, then migrate."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                entry_reference TEXT NOT NULL,
                iban TEXT NOT NULL,
                bank TEXT,
                amount REAL NOT NULL,
                currency TEXT,
                credit_debit_indicator TEXT,
                booking_date TEXT,
                creditor_name TEXT,
                debtor_name TEXT,
                remittance_information TEXT,
                PRIMARY KEY (entry_reference, iban)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS balances (
                iban TEXT PRIMARY KEY,
                bank TEXT,
                amount REAL,
                currency TEXT,
                balance_type TEXT,
                last_updated TEXT
            )
        """)
        conn.commit()
    migrate_db()
    _LOGGER.debug("Database initialized at %s", DB_PATH)


def migrate_db() -> None:
    """Migrate existing data from account_uid-keyed schema to iban-keyed schema."""
    with sqlite3.connect(DB_PATH) as conn:
        # Check if old transactions table has account_uid column
        cols = [row[1] for row in conn.execute("PRAGMA table_info(transactions)").fetchall()]
        if "account_uid" in cols and "iban" in cols:
            _LOGGER.info("Migrating transactions table from account_uid to iban as primary key")
            # Create new table with iban-based primary key
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transactions_new (
                    entry_reference TEXT NOT NULL,
                    iban TEXT NOT NULL,
                    bank TEXT,
                    amount REAL NOT NULL,
                    currency TEXT,
                    credit_debit_indicator TEXT,
                    booking_date TEXT,
                    creditor_name TEXT,
                    debtor_name TEXT,
                    remittance_information TEXT,
                    PRIMARY KEY (entry_reference, iban)
                )
            """)
            # Copy data — use iban column which was already stored
            conn.execute("""
                INSERT OR IGNORE INTO transactions_new
                SELECT entry_reference, iban, bank, amount, currency,
                       credit_debit_indicator, booking_date, creditor_name,
                       debtor_name, remittance_information
                FROM transactions
                WHERE iban IS NOT NULL
            """)
            conn.execute("DROP TABLE transactions")
            conn.execute("ALTER TABLE transactions_new RENAME TO transactions")
            _LOGGER.info("Transactions migration complete")

        # Check if old balances table has account_uid column
        cols = [row[1] for row in conn.execute("PRAGMA table_info(balances)").fetchall()]
        if "account_uid" in cols:
            _LOGGER.info("Migrating balances table from account_uid to iban as primary key")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS balances_new (
                    iban TEXT PRIMARY KEY,
                    bank TEXT,
                    amount REAL,
                    currency TEXT,
                    balance_type TEXT,
                    last_updated TEXT
                )
            """)
            conn.execute("""
                INSERT OR IGNORE INTO balances_new
                SELECT iban, bank, amount, currency, balance_type, last_updated
                FROM balances
                WHERE iban IS NOT NULL
            """)
            conn.execute("DROP TABLE balances")
            conn.execute("ALTER TABLE balances_new RENAME TO balances")
            _LOGGER.info("Balances migration complete")

        conn.commit()


def save_transactions(uid: str, iban: str, bank: str, transactions: list) -> int:
    """Save transactions to database keyed on iban, skip duplicates."""
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
                        entry_reference, iban, bank,
                        amount, currency, credit_debit_indicator,
                        booking_date, creditor_name, debtor_name,
                        remittance_information
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    entry_reference,
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
    """Save latest balance to database keyed on iban."""
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
                    iban, bank, amount, currency, balance_type, last_updated
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
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


def get_balance(iban: str) -> Optional[float]:
    """Get latest balance for an account by IBAN."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(
                "SELECT amount FROM balances WHERE iban = ?", (iban,)
            ).fetchone()
            return row[0] if row else None
    except Exception as err:
        _LOGGER.error("Error reading balance for %s: %s", iban, err)
        return None


# Whitelists — only these values are interpolated into SQL.
AGGREGATES = {
    "sum": "SUM",
    "avg": "AVG",
    "min": "MIN",
    "max": "MAX",
    "count": "COUNT",
    "total": "TOTAL",
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
    """Unused helper — kept for reference."""
    if (today.month, today.day) >= (anchor_month, anchor_day):
        return today.year
    return today.year - 1


def _resolve_period(period) -> tuple:
    """Return (date_from, date_to) as ISO date strings, or None."""
    if not period:
        return None, None
    return period.get("from") or None, period.get("to") or None


def get_transaction_total(
    iban: str,
    period=None,
    direction: str = "",
    matches: list = None,
    aggregate: str = "sum",
) -> float:
    """Aggregate stored transactions for one account by IBAN."""
    try:
        agg = AGGREGATES.get(str(aggregate).lower())
        if not agg:
            _LOGGER.error("Unknown aggregate %r, falling back to SUM", aggregate)
            agg = "SUM"

        column = "*" if agg == "COUNT" else "amount"

        clauses = ["iban = ?"]
        params = [iban]

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
