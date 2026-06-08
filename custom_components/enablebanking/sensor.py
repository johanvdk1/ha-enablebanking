"""Enable Banking sensors."""
import logging
from datetime import datetime
from homeassistant.components.sensor import SensorEntity, SensorStateClass, SensorDeviceClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up sensors from config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    sensors_config = entry.data.get("sensors", [])

    entities = []

    # Wait for first data
    data = coordinator.data or {}

    for uid, account_data in data.items():
        # Balance sensor
        entities.append(
            EnableBankingBalanceSensor(coordinator, uid, account_data)
        )

        # Transaction query sensors from config
        for sensor_cfg in sensors_config:
            entities.append(
                EnableBankingTransactionSensor(coordinator, uid, account_data, sensor_cfg)
            )

    async_add_entities(entities, True)


class EnableBankingBalanceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for account balance."""

    def __init__(self, coordinator, uid, account_data):
        super().__init__(coordinator)
        self._uid = uid
        self._iban = account_data["iban"]
        self._bank = account_data["bank"]
        self._attr_name = f"{self._bank} {self._iban} Balance"
        self._attr_unique_id = f"enablebanking_balance_{uid}"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_native_unit_of_measurement = "EUR"

    @property
    def native_value(self):
        data = self.coordinator.data.get(self._uid, {})
        balances = data.get("balances", [])
        for b in balances:
            if b.get("balance_type") == "ITAV":
                return float(b["balance_amount"]["amount"])
        return None

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data.get(self._uid, {})
        return {
            "iban": self._iban,
            "bank": self._bank,
            "balances": data.get("balances", []),
        }


class EnableBankingTransactionSensor(CoordinatorEntity, SensorEntity):
    """Sensor for querying transaction totals."""

    def __init__(self, coordinator, uid, account_data, sensor_cfg):
        super().__init__(coordinator)
        self._uid = uid
        self._iban = account_data["iban"]
        self._bank = account_data["bank"]
        self._sensor_cfg = sensor_cfg
        self._attr_name = sensor_cfg["name"]
        self._attr_unique_id = f"enablebanking_tx_{uid}_{sensor_cfg['name'].lower().replace(' ', '_')}"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_native_unit_of_measurement = "EUR"

    @property
    def native_value(self):
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
            # Direction filter
            if tx.get("credit_debit_indicator") != direction:
                continue

            # Date filter
            if date_from:
                booking_date = datetime.strptime(tx["booking_date"], "%Y-%m-%d").date()
                if booking_date < date_from:
                    continue

            # Creditor filter
            creditor = tx.get("creditor") or {}
            creditor_name = (creditor.get("name") or "").lower()
            if creditor_filter and creditor_filter not in creditor_name:
                continue

            total += float(tx["transaction_amount"]["amount"])

        return round(total, 2)

    @property
    def extra_state_attributes(self):
        return {
            "iban": self._iban,
            "bank": self._bank,
            "filter": self._sensor_cfg,
        }
