"""Enable Banking sensors."""
import logging
from datetime import datetime

from homeassistant.components.sensor import SensorEntity, SensorStateClass, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors from config entry."""
    coordinators = hass.data[DOMAIN][entry.entry_id]
    transaction_coordinator = coordinators["transaction_coordinator"]
    balance_coordinator = coordinators["balance_coordinator"]
    sensors_config = coordinators.get("yaml_config", {}).get("sensors", [])

    entities = []

    # Load accounts from sessions file directly so entities are always created
    # even when API calls fail due to rate limits
    import json
    from .const import SESSIONS_PATH
    try:
        with open(SESSIONS_PATH) as f:
            sessions = json.load(f)
        accounts = []
        for bank_name, session in sessions.items():
            for account in session.get("accounts", []):
                accounts.append({
                    "uid": account.get("uid"),
                    "iban": account.get("account_id", {}).get("iban", account.get("uid")),
                    "name": account.get("name", ""),
                    "bank": bank_name,
                })
    except Exception as err:
        _LOGGER.error("Could not load sessions file: %s", err)
        accounts = []

    _LOGGER.warning("enablebanking found %d accounts from sessions file", len(accounts))
    _LOGGER.warning("enablebanking sensors_config: %s", sensors_config)

    for account_data in accounts:
        uid = account_data["uid"]

        # Balance sensor
        entities.append(
            EnableBankingBalanceSensor(balance_coordinator, uid, account_data)
        )

        # Transaction query sensors
        for sensor_cfg in sensors_config:
            entities.append(
                EnableBankingTransactionSensor(
                    transaction_coordinator, uid, account_data, sensor_cfg
                )
            )

    async_add_entities(entities, True)


class EnableBankingBalanceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for account balance."""

    def __init__(self, coordinator, uid, account_data):
        """Initialize."""
        super().__init__(coordinator)
        self._uid = uid
        self._iban = account_data.get("iban", uid)
        self._bank = account_data.get("bank", "Unknown")
        self._attr_name = f"{self._bank} {self._iban} Balance"
        self._attr_unique_id = f"enablebanking_balance_{uid}"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_native_unit_of_measurement = "EUR"

    @property
    def native_value(self):
        """Return balance."""
        if not self.coordinator.data:
            return None
        data = self.coordinator.data.get(self._uid, {})
        for b in data.get("balances", []):
            if b.get("balance_type") == "ITAV":
                return float(b["balance_amount"]["amount"])
        return None

    @property
    def extra_state_attributes(self):
        """Return extra attributes."""
        if not self.coordinator.data:
            return {"iban": self._iban, "bank": self._bank}
        data = self.coordinator.data.get(self._uid, {})
        return {
            "iban": self._iban,
            "bank": self._bank,
            "balances": data.get("balances", []),
        }


class EnableBankingTransactionSensor(CoordinatorEntity, SensorEntity):
    """Sensor for querying transaction totals."""

    def __init__(self, coordinator, uid, account_data, sensor_cfg):
        """Initialize."""
        super().__init__(coordinator)
        self._uid = uid
        self._iban = account_data.get("iban", uid)
        self._bank = account_data.get("bank", "Unknown")
        self._sensor_cfg = sensor_cfg
        self._attr_name = sensor_cfg["name"]
        self._attr_unique_id = (
            f"enablebanking_tx_{uid}_{sensor_cfg['name'].lower().replace(' ', '_')}"
        )
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_native_unit_of_measurement = "EUR"

    @property
    def native_value(self):
        """Return transaction total."""
        if not self.coordinator.data:
            return None
        data = self.coordinator.data.get(self._uid, {})
        transactions = data.get("transactions", [])

        creditor_filter = self._sensor_cfg.get("creditor", "").lower()
        period = self._sensor_cfg.get("period", "year")
        direction = self._sensor_cfg.get("direction", "DBIT")

        now = datetime.now()
        if period == "year":
            date_from = datetime(now.year, 1, 1).date()
        elif period == "month":
            date_from = datetime(now.year, now.month, 1).date()
        else:
            date_from = None

        total = 0.0
        for tx in transactions:
            if tx.get("credit_debit_indicator") != direction:
                continue
            if date_from:
                try:
                    booking_date = datetime.strptime(tx["booking_date"], "%Y-%m-%d").date()
                    if booking_date < date_from:
                        continue
                except (ValueError, KeyError):
                    continue
            creditor = tx.get("creditor") or {}
            creditor_name = (creditor.get("name") or "").lower()
            if creditor_filter and creditor_filter not in creditor_name:
                continue
            try:
                total += float(tx["transaction_amount"]["amount"])
            except (ValueError, KeyError):
                continue

        return round(total, 2)

    @property
    def extra_state_attributes(self):
        """Return extra attributes."""
        return {
            "iban": self._iban,
            "bank": self._bank,
            "filter": self._sensor_cfg,
        }
