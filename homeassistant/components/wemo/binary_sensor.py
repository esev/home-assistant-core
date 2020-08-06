"""Support for WeMo binary sensors."""
import logging

from pywemo.ouimeaux_device.api.service import ActionException

from homeassistant.components.binary_sensor import BinarySensorEntity

from . import async_get_wemo_device
from .entity import WemoSubscriptionEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up WeMo binary sensors."""
    device = await async_get_wemo_device(hass, config_entry.data, remove_cache=True)
    async_add_entities([WemoBinarySensor(device)])


class WemoBinarySensor(WemoSubscriptionEntity, BinarySensorEntity):
    """Representation a WeMo binary sensor."""

    def _update(self, force_update=True):
        """Update the sensor state."""
        try:
            self._state = self.wemo.get_state(force_update)

            if not self._available:
                _LOGGER.info("Reconnected to %s", self.name)
                self._available = True
        except (AttributeError, ActionException) as err:
            _LOGGER.warning("Could not update status for %s (%s)", self.name, err)
            self._available = False
            self.wemo.reconnect_with_device()
