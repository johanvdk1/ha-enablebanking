"""Config flow for Enable Banking."""
import logging
import json
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from .const import DOMAIN, DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class EnableBankingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Enable Banking."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            try:
                sessions = json.loads(user_input["sessions"])
                return self.async_create_entry(
                    title="Enable Banking",
                    data={
                        "app_id": user_input["app_id"],
                        "private_key": user_input["private_key"],
                        "sessions": sessions,
                        "sensors": json.loads(user_input.get("sensors", "[]")),
                        "scan_interval": user_input.get("scan_interval", DEFAULT_SCAN_INTERVAL),
                    },
                )
            except Exception as e:
                _LOGGER.error("Config error: %s", e)
                errors["base"] = "invalid_config"

        schema = vol.Schema({
            vol.Required("app_id"): str,
            vol.Required("private_key"): str,
            vol.Required("sessions"): str,
            vol.Optional("sensors", default="[]"): str,
            vol.Optional("scan_interval", default=DEFAULT_SCAN_INTERVAL): int,
        })

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "app_id_help": "Your Enable Banking application ID",
                "sessions_help": "Paste the contents of your sessions.json file",
                "sensors_help": 'JSON array of sensor configs, e.g. [{"name": "Luminus This Year", "creditor": "luminus", "period": "year", "direction": "DBIT"}]',
            }
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return EnableBankingOptionsFlow(config_entry)


class EnableBankingOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow."""

    def __init__(self, config_entry):
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        errors = {}

        if user_input is not None:
            try:
                return self.async_create_entry(
                    title="",
                    data={
                        "sensors": json.loads(user_input.get("sensors", "[]")),
                        "scan_interval": user_input.get("scan_interval", DEFAULT_SCAN_INTERVAL),
                    },
                )
            except Exception as e:
                _LOGGER.error("Options error: %s", e)
                errors["base"] = "invalid_config"

        current_sensors = json.dumps(
            self._config_entry.data.get("sensors", []), indent=2
        )

        schema = vol.Schema({
            vol.Optional("sensors", default=current_sensors): str,
            vol.Optional("scan_interval", default=self._config_entry.data.get("scan_interval", DEFAULT_SCAN_INTERVAL)): int,
        })

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )
