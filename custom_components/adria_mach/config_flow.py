"""Native login, assigned-vehicle selection and identity-preserving reauth."""

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from . import create_client
from .client import AuthenticationError, MachError
from .const import (
    CONF_EQUIPMENT,
    CONF_MACH_ID,
    CONF_ONOFF_LIGHTS,
    DOMAIN,
    EQUIPMENT_OPTIONS,
    LIGHT_OPTIONS,
)

CREDENTIALS = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),
    }
)


class MachConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._credentials = {}
        self._devices = ()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return MachOptionsFlow()

    async def async_step_user(self, user_input=None):
        return await self._login("user", user_input)

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        return await self._login("reauth_confirm", user_input)

    async def _login(self, step_id, user_input):
        errors = {}
        if user_input is not None:
            client = create_client(self.hass)
            try:
                devices = await client.authenticate(
                    user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
                )
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except MachError:
                errors["base"] = "cannot_connect"
            else:
                if step_id == "reauth_confirm":
                    entry = self._get_reauth_entry()
                    if entry.data[CONF_MACH_ID] not in {device.id for device in devices}:
                        errors["base"] = "device_not_assigned"
                    else:
                        return self.async_update_reload_and_abort(entry, data_updates=user_input)
                elif not devices:
                    errors["base"] = "no_supported_devices"
                else:
                    self._credentials = dict(user_input)
                    self._devices = devices
                    if len(devices) == 1:
                        return await self._create(devices[0].id)
                    return await self.async_step_vehicle()
            finally:
                await client.close()
        return self.async_show_form(step_id=step_id, data_schema=CREDENTIALS, errors=errors)

    async def async_step_vehicle(self, user_input=None):
        if user_input is not None:
            if user_input[CONF_MACH_ID] not in {device.id for device in self._devices}:
                return self.async_abort(reason="device_not_assigned")
            return await self._create(user_input[CONF_MACH_ID])
        # Options have no default; selecting among assigned vehicles is explicit.
        return self.async_show_form(
            step_id="vehicle",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MACH_ID): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(
                                    value=device.id, label=f"{index + 1}. {device.name}"
                                )
                                for index, device in enumerate(self._devices)
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    async def _create(self, device_id):
        await self.async_set_unique_id(device_id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title="Adria MACH",
            data={
                **self._credentials,
                CONF_MACH_ID: device_id,
            },
        )


class MachOptionsFlow(config_entries.OptionsFlowWithReload):
    """Entry-local compatibility choices; no actuator experiment or inference."""

    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            chosen = user_input.get(CONF_ONOFF_LIGHTS)
            equipment = user_input.get(
                CONF_EQUIPMENT, self.config_entry.options.get(CONF_EQUIPMENT, [])
            )
            if (
                type(chosen) is not list
                or any(type(item) is not str or item not in LIGHT_OPTIONS for item in chosen)
                or len(set(chosen)) != len(chosen)
            ):
                errors["base"] = "invalid_light_selection"
            elif (
                type(equipment) is not list
                or any(type(item) is not str or item not in EQUIPMENT_OPTIONS for item in equipment)
                or len(set(equipment)) != len(equipment)
            ):
                errors["base"] = "invalid_equipment_selection"
            else:
                return self.async_create_entry(
                    data={
                        **self.config_entry.options,
                        CONF_ONOFF_LIGHTS: list(chosen),
                        CONF_EQUIPMENT: list(equipment),
                    }
                )
        return self.async_show_form(
            step_id="init",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ONOFF_LIGHTS,
                        default=list(self.config_entry.options.get(CONF_ONOFF_LIGHTS, [])),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=list(LIGHT_OPTIONS),
                            multiple=True,
                            translation_key="onoff_lights",
                        )
                    ),
                    vol.Optional(
                        CONF_EQUIPMENT,
                        default=list(self.config_entry.options.get(CONF_EQUIPMENT, [])),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=list(EQUIPMENT_OPTIONS),
                            multiple=True,
                            translation_key="identified_equipment",
                        )
                    ),
                }
            ),
        )
