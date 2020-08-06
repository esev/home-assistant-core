"""Config flow for Wemo."""
import logging
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.ssdp import (
    ATTR_SSDP_LOCATION,
    ATTR_UPNP_FRIENDLY_NAME,
    ATTR_UPNP_SERIAL,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import DOMAIN, CannotDeterminePortError, ConnectError, async_get_wemo_device

_LOGGER = logging.getLogger(__name__)

CONFIG_ENTRY_VERSION = 2

ERROR_CANNOT_CONNECT = "cannot_connect"
ERROR_CANNOT_DETERMINE_PORT = "cannot_determine_port"
REASON_NO_DEVICES_FOUND = "no_devices_found"

STEP_ID_CONFIRM = "confirm"
STEP_ID_USER = "user"


@config_entries.HANDLERS.register(DOMAIN)
class WemoFlowHandler(config_entries.ConfigFlow):
    """Config Flow for Wemo."""

    VERSION = CONFIG_ENTRY_VERSION
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    @property
    def _wemo_data(self) -> Dict[str, Any]:
        return self.hass.data.setdefault(DOMAIN, {})

    @property
    def _discovery_info(self) -> Dict[str, DiscoveryInfoType]:
        return self._wemo_data.setdefault("discovery_info", {})

    async def _async_set_unique_id_and_update(
        self, user_input: ConfigType, unique_id: str
    ) -> None:
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured(user_input)

    async def async_step_import(
        self, user_input: Optional[ConfigType] = None
    ) -> Dict[str, Any]:
        """Handle a flow initiated by configuration file."""
        return await self.async_step_user(user_input)

    async def async_step_user(
        self, user_input: Optional[ConfigType] = None
    ) -> Dict[str, Any]:
        """Handle a discovered device."""
        _LOGGER.debug("async_step_user: %s", user_input)
        errors = {}

        user_input = user_input or {}  # Input exactly as supplied by the user.
        data = {CONF_PORT: 0, **user_input}  # User input augmented with defaults.
        port_field_marker = vol.Optional
        if user_input:
            try:
                device = await async_get_wemo_device(self.hass, data)
            except CannotDeterminePortError:
                # Port is required if it cannot be determined automatically.
                port_field_marker = vol.Required
                errors["base"] = ERROR_CANNOT_DETERMINE_PORT
            except ConnectError:
                _LOGGER.exception("Failed to connect")
                errors["base"] = ERROR_CANNOT_CONNECT
            else:
                if not self.unique_id:
                    await self._async_set_unique_id_and_update(
                        user_input, device.serialnumber
                    )
                # Device was connected. Add the device to hass.
                return self.async_create_entry(title=device.name, data=data)

        # Ask the user to fill in the configuration for the device.
        fields = {
            vol.Required(
                CONF_HOST, default=user_input.get(CONF_HOST, vol.UNDEFINED)
            ): str,
            port_field_marker(
                CONF_PORT, default=user_input.get(CONF_PORT, vol.UNDEFINED)
            ): int,
        }
        return self.async_show_form(
            step_id=STEP_ID_USER, data_schema=vol.Schema(fields), errors=errors
        )

    async def async_step_confirm(
        self, user_input: Optional[ConfigType] = None
    ) -> Dict[str, Any]:
        """Handle user-confirmation of discovered node."""
        context = self.context  # pylint: disable=no-member
        if user_input is not None:  # User has confirmed this flow.
            # Go to the user step next. It has error handling that can help if
            # the device information is incorrect.
            return await self.async_step_user(context.get("user_input"))

        # The WeMo component previously had a single ConfigEntry Discovery ConfigFlow
        # with multiple devices sharing the same ConfigEntry. Check to see if a device
        # entry was already setup. This avoids prompting the user to reconfigure the
        # area for the device.
        dev_reg = await self.hass.helpers.device_registry.async_get_registry()
        if dev_reg.async_get_device({(DOMAIN, self.unique_id)}, set()):
            return await self.async_step_user(context.get("user_input"))

        return self.async_show_form(
            step_id=STEP_ID_CONFIRM,
            description_placeholders=context.get("title_placeholders", {}),
        )

    async def async_step_ssdp(
        self, discovery_info: DiscoveryInfoType
    ) -> Dict[str, Any]:
        """Handle SSDP discovery."""
        location_url = urlparse(discovery_info[ATTR_SSDP_LOCATION])
        unique_id = discovery_info[ATTR_UPNP_SERIAL]
        user_input = {
            CONF_HOST: location_url.hostname,
            CONF_PORT: location_url.port,
        }

        # Save a copy of the discovery info: Since the SSDP information is only ever
        # delivered once, and there is no other way to recover this information when
        # an entry is unignored, this information is saved in order to support unignoring
        # a device. Note that this also means that unignore will not work if the SSDP
        # discovery is not received for a device (after hass is restarted, for example).
        self._discovery_info[unique_id] = discovery_info

        self.context.update(  # pylint: disable=no-member
            {
                "user_input": user_input,
                "title_placeholders": {"name": discovery_info[ATTR_UPNP_FRIENDLY_NAME]},
            }
        )
        await self._async_set_unique_id_and_update(user_input, unique_id)
        return await self.async_step_confirm()

    async def async_step_unignore(self, user_input: ConfigType) -> Dict[str, Any]:
        """Rediscover a config entry by it's unique_id."""
        discovery_info = self._discovery_info.get(user_input["unique_id"])
        if discovery_info:
            return await self.async_step_ssdp(discovery_info)
        _LOGGER.error("No discovery_info for device: %s", user_input["unique_id"])
        # See 'Save a copy of the discovery info' comment in async_step_ssdp.
        return self.async_abort(reason=REASON_NO_DEVICES_FOUND)
