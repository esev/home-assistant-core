"""WeMo device setup and static configuration."""
import logging
from typing import Optional, Tuple

import pywemo
import requests
import voluptuous as vol


from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.components.fan import DOMAIN as FAN_DOMAIN
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import (
    CONF_DOMAIN,
    CONF_HOST,
    CONF_PORT,
    EVENT_HOMEASSISTANT_STOP,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.singleton import singleton
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN

# Mapping from Wemo model_name to domain.
WEMO_MODEL_DISPATCH = {
    "Bridge": LIGHT_DOMAIN,
    "CoffeeMaker": SWITCH_DOMAIN,
    "Dimmer": LIGHT_DOMAIN,
    "Humidifier": FAN_DOMAIN,
    "Insight": SWITCH_DOMAIN,
    "LightSwitch": SWITCH_DOMAIN,
    "Maker": SWITCH_DOMAIN,
    "Motion": BINARY_SENSOR_DOMAIN,
    "Sensor": BINARY_SENSOR_DOMAIN,
    "Socket": SWITCH_DOMAIN,
}

_LOGGER = logging.getLogger(__name__)


def coerce_host_port(value: str) -> Tuple[str, int]:
    """Validate that provided value is either just host or host:port.

    Returns (host, 0) or (host, port) respectively.
    """
    host, _, port = value.partition(":")

    if not host:
        raise vol.Invalid("host cannot be empty")

    if port:
        port = cv.port(port)
    else:
        port = 0

    return host, port


CONF_STATIC = "static"

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_STATIC, default=[]): vol.Schema(
                    [vol.All(cv.string, coerce_host_port)]
                ),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config) -> bool:
    """Set up for WeMo devices."""
    hass.data.setdefault(DOMAIN, {})
    # Keep track of WeMo device subscriptions for push updates
    registry = hass.data[DOMAIN]["registry"] = pywemo.SubscriptionRegistry()
    await hass.async_add_executor_job(registry.start)

    def stop_wemo(event):
        """Shutdown Wemo subscriptions and subscription thread on exit."""
        _LOGGER.debug("Shutting down WeMo event subscriptions")
        registry.stop()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop_wemo)

    # Check for static hosts in the config.
    wemo_config = config.get(DOMAIN, {})
    for host, port in wemo_config.get(CONF_STATIC, []):
        data = {CONF_HOST: host, CONF_PORT: port}
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_IMPORT}, data=data
            )
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a wemo config entry.

    Verify that the device is setup correctly. This will raise a ConfigEntryNotReady
    exception if the device is not yet online.
    """
    device = await async_get_wemo_device(hass, entry.data)

    domain = WEMO_MODEL_DISPATCH.get(device.model_name, SWITCH_DOMAIN)
    if entry.data.get(CONF_DOMAIN) != domain:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_DOMAIN: domain}
        )
    hass.async_create_task(hass.config_entries.async_forward_entry_setup(entry, domain))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    domain = entry.data[CONF_DOMAIN]
    return await hass.config_entries.async_forward_entry_unload(entry, domain)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Handle migration of a previous version config entry."""
    if entry.version == 1:
        # The WeMo component previously had a single ConfigEntry Discovery ConfigFlow
        # with multiple devices sharing the same ConfigEntry. That old ConfigEntry
        # can be removed once all devices have been migrated to new ConfigEntries.
        # A device will be associated with 2 ConfigEntries (old & new) when it has
        # been migrated.
        dev_reg = hass.helpers.device_registry
        devices = await dev_reg.async_get_registry()
        device_entries = dev_reg.async_entries_for_config_entry(devices, entry.entry_id)
        if all(len(device.config_entries) > 1 for device in device_entries):
            hass.async_create_task(hass.config_entries.async_remove(entry.entry_id))
        return False
    return True


async def async_get_wemo_device(
    hass: HomeAssistant, config_data: ConfigType, remove_cache: Optional[bool] = False
) -> pywemo.WeMoDevice:
    """Create a WeMoDevice instance or return one from the cache."""
    host, port = config_data[CONF_HOST], config_data[CONF_PORT]
    cache = hass.data.setdefault(DOMAIN, {}).setdefault("pywemo_wemodevice_cache", {})
    cache_key = f"{host}:{port}"
    device = (cache.pop if remove_cache else cache.get)(cache_key, None)
    if device is not None:
        return device

    device = await hass.async_add_executor_job(_get_wemo_device, host, port)
    cache[cache_key] = device
    return device


def _get_wemo_device(host: str, port: int) -> pywemo.WeMoDevice:
    """Handle a static config."""
    url = pywemo.setup_url_for_address(host, port)
    if url is None:
        raise CannotDeterminePortError(
            "Unable to get description url for WeMo at: %s"
            % (f"{host}:{port}" if port else host)
        )

    try:
        return pywemo.discovery.device_from_description(url, None)
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as err:
        raise ConnectError(f"Unable to access WeMo at {url} ({err})") from err


class ConnectError(ConfigEntryNotReady):
    """Cannot connect to the wemo device."""


class CannotDeterminePortError(ConnectError):
    """Error to indicate the port cannot be determined automatically."""
