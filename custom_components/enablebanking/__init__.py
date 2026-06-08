"""Enable Banking integration for Home Assistant."""
import logging
from datetime import timedelta

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import EnableBankingAPI
from .const import (
    DOMAIN,
    CONF_APP_ID,
    CONF_SENSORS,
    CONF_TRANSACTION_INTERVAL,
    CONF_BALANCE_INTERVAL,
    DEFAULT_TRANSACTION_INTERVAL,
    DEFAULT_BALANCE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

SENSOR_SCHEMA = vol.Schema({
    vol.Required("name"): cv.string,
    vol.Optional("creditor", default=""): cv.string,
    vol.Optional("period", default="year"): vol.In(["year", "month", "all"]),
    vol.Optional("direction", default="DBIT"): vol.In(["DBIT", "CRDT"]),
})

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Optional(CONF_TRANSACTION_INTERVAL, default=DEFAULT_TRANSACTION_INTERVAL): cv.positive_int,
        vol.Optional(CONF_BALANCE_INTERVAL, default=DEFAULT_BALANCE_INTERVAL): cv.positive_int,
        vol.Optional(CONF_SENSORS, default=[]): vol.All(
            cv.ensure_list, [SENSOR_SCHEMA]
        ),
    })
}, extra=vol.ALLOW_EXTRA)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up Enable Banking from YAML config."""
    hass.data.setdefault(DOMAIN, {})
    if DOMAIN in config:
        hass.data[DOMAIN]["yaml_config"] = config[DOMAIN]
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Enable Banking from a config entry."""
    yaml_config = hass.data.get(DOMAIN, {}).get("yaml_config", {})

    api = EnableBankingAPI(app_id=entry.data[CONF_APP_ID])

    transaction_interval = yaml_config.get(CONF_TRANSACTION_INTERVAL, DEFAULT_TRANSACTION_INTERVAL)
    balance_interval = yaml_config.get(CONF_BALANCE_INTERVAL, DEFAULT_BALANCE_INTERVAL)

    async def async_update_transactions():
        try:
            return await hass.async_add_executor_job(api.fetch_transactions)
        except Exception as err:
            raise UpdateFailed(f"Error fetching transactions: {err}") from err

    async def async_update_balances():
        try:
            return await hass.async_add_executor_job(api.fetch_balances)
        except Exception as err:
            raise UpdateFailed(f"Error fetching balances: {err}") from err

    transaction_coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_transactions",
        update_method=async_update_transactions,
        update_interval=timedelta(minutes=transaction_interval),
    )

    balance_coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_balances",
        update_method=async_update_balances,
        update_interval=timedelta(minutes=balance_interval),
    )

    await transaction_coordinator.async_config_entry_first_refresh()

    try:
        await balance_coordinator.async_config_entry_first_refresh()
    except Exception as err:
        _LOGGER.warning("Could not fetch initial balances: %s. Will retry later.", err)

    hass.data[DOMAIN][entry.entry_id] = {
        "transaction_coordinator": transaction_coordinator,
        "balance_coordinator": balance_coordinator,
        "yaml_config": yaml_config,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry_data = hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
