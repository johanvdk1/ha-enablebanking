"""Config flow for Enable Banking."""
import json
import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .const import DOMAIN, DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class EnableBankingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Enable Banking."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            try:
                sessions = json.loads(user_input["sessions"])
                sensors = json.loads(user_input["sensors"])
                return self.async_create_entry(
                    title="Enable Banking",
                    data={
                        "app_id": user_input["app_id"],
                        "private_key": user_input["private_key"],
                        "sessions": sessions,
                        "sensors": sensors,
                        "scan_interval": user_input.get("scan_interval", DEFAULT_SCAN_INTERVAL),
                    },
                )
            except json.JSONDecodeError:
                errors["base"] = "invalid_json"
            except Exception as err:
                _LOGGER.error("Unexpected error: %s", err)
                errors["base"] = "unknown"

        schema = vol.Schema({
            vol.Required("app_id"): str,
            vol.Required("private_key"): str,
            vol.Required("sessions"): str,
            vol.Required("sensors", default="[]"): str,
            vol.Optional("scan_interval", default=DEFAULT_SCAN_INTERVAL): int,
        })

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return options flow."""
        return EnableBankingOptionsFlow(config_entry)


class EnableBankingOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow."""

    def __init__(self, config_entry):
        """Initialize."""
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage options."""
        errors = {}

        if user_input is not None:
            try:
                sensors = json.loads(user_input["sensors"])
                return self.async_create_entry(
                    title="",
                    data={
                        "sensors": sensors,
                        "scan_interval": user_input["scan_interval"],
                    },
                )
            except json.JSONDecodeError:
                errors["base"] = "invalid_json"

        schema = vol.Schema({
            vol.Required(
                "sensors",
                default=json.dumps(self._config_entry.data.get("sensors", []), indent=2),
            ): str,
            vol.Optional(
                "scan_interval",
                default=self._config_entry.data.get("scan_interval", DEFAULT_SCAN_INTERVAL),
            ): int,
        })

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )
