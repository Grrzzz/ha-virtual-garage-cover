"""Config flow for Tri-State Cover integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_CLOSED_SENSOR,
    CONF_OPEN_SENSOR,
    CONF_SWITCH_ENTITY,
    CONF_TOGGLE_DELAY,
    CONF_TRAVEL_TIME,
    DEFAULT_TOGGLE_DELAY,
    DEFAULT_TRAVEL_TIME,
    DOMAIN,
)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SWITCH_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="switch"),
        ),
        vol.Required(
            CONF_TRAVEL_TIME, default=DEFAULT_TRAVEL_TIME
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=5,
                max=120,
                step=1,
                unit_of_measurement="s",
                mode=selector.NumberSelectorMode.BOX,
            ),
        ),
        vol.Optional(CONF_CLOSED_SENSOR): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="binary_sensor"),
        ),
        vol.Optional(CONF_OPEN_SENSOR): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="binary_sensor"),
        ),
        vol.Optional(
            CONF_TOGGLE_DELAY, default=DEFAULT_TOGGLE_DELAY
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0.1,
                max=1.0,
                step=0.05,
                unit_of_measurement="s",
                mode=selector.NumberSelectorMode.BOX,
            ),
        ),
    }
)


class TriStateCoverConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tri-State Cover."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Check that the switch entity isn't already configured
            await self.async_set_unique_id(user_input[CONF_SWITCH_ENTITY])
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"Tri-State Cover ({user_input[CONF_SWITCH_ENTITY]})",
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return TriStateCoverOptionsFlow(config_entry)


class TriStateCoverOptionsFlow(OptionsFlow):
    """Handle options flow for Tri-State Cover."""

    def __init__(self, config_entry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.data

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_TRAVEL_TIME,
                        default=current.get(CONF_TRAVEL_TIME, DEFAULT_TRAVEL_TIME),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=5,
                            max=120,
                            step=1,
                            unit_of_measurement="s",
                            mode=selector.NumberSelectorMode.BOX,
                        ),
                    ),
                    vol.Optional(
                        CONF_CLOSED_SENSOR,
                        description={
                            "suggested_value": current.get(CONF_CLOSED_SENSOR)
                        },
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="binary_sensor"),
                    ),
                    vol.Optional(
                        CONF_OPEN_SENSOR,
                        description={
                            "suggested_value": current.get(CONF_OPEN_SENSOR)
                        },
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="binary_sensor"),
                    ),
                    vol.Optional(
                        CONF_TOGGLE_DELAY,
                        default=current.get(CONF_TOGGLE_DELAY, DEFAULT_TOGGLE_DELAY),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0.1,
                            max=1.0,
                            step=0.05,
                            unit_of_measurement="s",
                            mode=selector.NumberSelectorMode.BOX,
                        ),
                    ),
                }
            ),
        )
