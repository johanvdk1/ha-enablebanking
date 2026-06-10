"""Enable Banking sensors."""
import json
import logging
from datetime import datetime

from homeassistant.components.sensor import SensorEntity, SensorStateClass, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SESSIONS_PATH
from .database import get_balance, get_transaction_total

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

    # Load accounts from sessions file in executor to avoid blocking event loop
    def _load_accounts():
        try:
            with open(SESSIONS_PATH) as f:
                sessions = json.load(f)
            result = []
            for bank_name, session in sessions.items():
                for account in session.get("accounts", []):
                    result.append({
                        "uid": account.get("uid"),
                        "iban": account.get("account_id", {}).get("iban", account.get("uid")),
                        "name": account.get("name", ""),
                        "bank": bank_name,
                    })
            return result
        except Exception as err:
            _LOGGER.error("Could not load sessions file: %s", err)
            return []

    accounts = await hass.async_add_executor_job(_load_accounts)

    entities = []

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

    # Rate limit diagnostic sensors
    entities.append(EnableBankingRateLimitSensor(transaction_coordinator, "Transaction"))
    entities.append(EnableBankingRateLimitSensor(balance_coordinator, "Balance"))

    async_add_entities(entities, False)


class EnableBankingBalanceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for account balance - reads from database."""

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
    def device_info(self):
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, self._uid)},
            "name": f"{self._bank} {self._iban}",
            "manufacturer": self._bank,
            "model": "Bank Account",
        }

    @property
    def native_value(self):
        """Return balance from database."""
        return get_balance(self._uid)

    @property
    def extra_state_attributes(self):
        """Return extra attributes."""
        return {
            "iban": self._iban,
            "bank": self._bank,
        }


class EnableBankingTransactionSensor(CoordinatorEntity, SensorEntity):
    """Sensor for querying transaction totals - reads from database."""

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
    def device_info(self):
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, self._uid)},
            "name": f"{self._bank} {self._iban}",
            "manufacturer": self._bank,
            "model": "Bank Account",
        }

    @property
    def native_value(self):
        """Return transaction total from database."""
        return get_transaction_total(
            uid=self._uid,
            creditor_filter=self._sensor_cfg.get("creditor", ""),
            period=self._sensor_cfg.get("period", "year"),
            direction=self._sensor_cfg.get("direction", "DBIT"),
        )

    @property
    def extra_state_attributes(self):
        """Return extra attributes."""
        return {
            "iban": self._iban,
            "bank": self._bank,
            "filter": self._sensor_cfg,
        }


class EnableBankingRateLimitSensor(CoordinatorEntity, SensorEntity):
    """Diagnostic sensor for rate limit status."""

    def __init__(self, coordinator, endpoint: str):
        """Initialize."""
        super().__init__(coordinator)
        self._endpoint = endpoint
        self._attr_name = f"Rate Limit {endpoint}"
        self._attr_unique_id = f"enablebanking_rate_limit_{endpoint.lower()}"
        self._attr_icon = "mdi:alert"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def device_info(self):
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, "service")},
            "name": "Enable Banking",
            "manufacturer": "Enable Banking",
            "model": "Service",
        }

    @property
    def native_value(self):
        """Return on if rate limited."""
        if not self.coordinator.data:
            return "off"
        return "on" if self.coordinator.data.get("rate_limited", False) else "off"

    @property
    def extra_state_attributes(self):
        """Return extra attributes."""
        return {"endpoint": self._endpoint}
