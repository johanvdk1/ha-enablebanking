"""Config flow for Enable Banking."""
import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .const import DOMAIN, CONF_APP_ID

_LOGGER = logging.getLogger(__name__)


class EnableBankingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Enable Banking."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            return self.async_create_entry(
                title="Enable Banking",
                data={
                    CONF_APP_ID: user_input[CONF_APP_ID],
                },
            )

        schema = vol.Schema({
            vol.Required(CONF_APP_ID): str,
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
        if user_input is not None:
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({}),
            description_placeholders={
                "config_note": "Edit sensors and intervals in configuration.yaml under the enablebanking key."
            },
        )
