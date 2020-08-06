"""Tests for the wemo component."""
import requests

from homeassistant.components.wemo import (
    CONF_STATIC,
    SWITCH_DOMAIN,
    WEMO_MODEL_DISPATCH,
)
from homeassistant.components.wemo.config_flow import CONFIG_ENTRY_VERSION
from homeassistant.components.wemo.const import DOMAIN
from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.const import CONF_DOMAIN, CONF_HOST, CONF_PORT
from homeassistant.setup import async_setup_component

from .conftest import MOCK_HOST, MOCK_NAME, MOCK_PORT, MOCK_SERIAL_NUMBER

from tests.async_mock import patch
from tests.common import MockConfigEntry

CONFIG_DICT = {
    DOMAIN: {
        CONF_STATIC: [f"{MOCK_HOST}:{MOCK_PORT}"],
    },
}


async def test_config_no_config(hass):
    """Component setup succeeds when there are no config entry for the domain."""
    assert await async_setup_component(hass, DOMAIN, {})


async def test_config_no_static(hass):
    """Component setup succeeds when there are no static config entries."""
    assert await async_setup_component(hass, DOMAIN, {DOMAIN: {}})


async def test_static_duplicate_static_entry(hass, pywemo_device):
    """Duplicate static entries are merged into a single entity."""
    static_config_entry = f"{MOCK_HOST}:{MOCK_PORT}"
    assert await async_setup_component(
        hass,
        DOMAIN,
        {
            DOMAIN: {
                CONF_STATIC: [
                    static_config_entry,
                    static_config_entry,
                ],
            },
        },
    )
    await hass.async_block_till_done()
    entity_reg = await hass.helpers.entity_registry.async_get_registry()
    entity_entries = list(entity_reg.entities.values())
    assert len(entity_entries) == 1

    # Unload the entry to trigger any cleanups.
    assert await hass.config_entries.async_unload(entity_entries[0].config_entry_id)
    await hass.async_block_till_done()


async def test_static_config_with_port(hass, pywemo_device):
    """Static device with host and port is added and removed."""
    assert await async_setup_component(hass, DOMAIN, CONFIG_DICT)
    await hass.async_block_till_done()
    entity_reg = await hass.helpers.entity_registry.async_get_registry()
    entity_entries = list(entity_reg.entities.values())
    assert len(entity_entries) == 1

    # Unload the entry to trigger any cleanups.
    assert await hass.config_entries.async_unload(entity_entries[0].config_entry_id)
    await hass.async_block_till_done()


async def test_static_config_without_port(hass, pywemo_device):
    """Static device with host and no port is added and removed."""
    assert await async_setup_component(
        hass,
        DOMAIN,
        {
            DOMAIN: {
                CONF_STATIC: [MOCK_HOST],
            },
        },
    )
    await hass.async_block_till_done()
    entity_reg = await hass.helpers.entity_registry.async_get_registry()
    entity_entries = list(entity_reg.entities.values())
    assert len(entity_entries) == 1

    # Unload the entry to trigger any cleanups.
    assert await hass.config_entries.async_unload(entity_entries[0].config_entry_id)
    await hass.async_block_till_done()


async def test_static_config_with_invalid_host(hass):
    """Component setup fails if a static host is invalid."""
    setup_success = await async_setup_component(
        hass,
        DOMAIN,
        {
            DOMAIN: {
                CONF_STATIC: [""],
            },
        },
    )
    assert setup_success is False


async def test_static_config_update(hass, pywemo_device):
    """The host/port is updated when the configuration changes."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "old_host", CONF_PORT: 111},
        source=SOURCE_IMPORT,
        title=MOCK_NAME,
        unique_id=MOCK_SERIAL_NUMBER,
        version=CONFIG_ENTRY_VERSION,
    )
    entry.add_to_hass(hass)

    assert await async_setup_component(hass, DOMAIN, CONFIG_DICT)
    await hass.async_block_till_done()

    assert entry.data[CONF_HOST] == MOCK_HOST
    assert entry.data[CONF_PORT] == MOCK_PORT
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_v1_migration_keeps_old_integration(hass, pywemo_device):
    """Test that the v1 config entry is not migrated if it is still in use."""
    v1_entry = MockConfigEntry(
        domain=DOMAIN,
        source=SOURCE_IMPORT,
        title=MOCK_NAME,
        unique_id=DOMAIN,
        version=1,
    )
    v1_entry.add_to_hass(hass)
    dev_registry = await hass.helpers.device_registry.async_get_registry()
    dev_registry.async_get_or_create(
        config_entry_id=v1_entry.entry_id,
        identifiers={("serial_number", MOCK_SERIAL_NUMBER)},
    )

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    # Expect the config entry was kept.
    assert len(hass.config_entries.async_entries()) == 1


async def test_v1_migration_deletes_old_integration(hass, pywemo_device):
    """Test removal of the v1 config entry during migration."""
    v1_entry = MockConfigEntry(
        domain=DOMAIN,
        source=SOURCE_IMPORT,
        title=MOCK_NAME,
        unique_id=DOMAIN,
        version=1,
    )
    v1_entry.add_to_hass(hass)
    domain = WEMO_MODEL_DISPATCH.get(pywemo_device.model_name)
    v2_entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: MOCK_HOST, CONF_PORT: MOCK_PORT, CONF_DOMAIN: domain},
        title=MOCK_NAME,
        unique_id=MOCK_SERIAL_NUMBER,
        version=CONFIG_ENTRY_VERSION,
    )
    v2_entry.add_to_hass(hass)
    assert len(hass.config_entries.async_entries()) == 2

    # Create a device that references both the v1 & v2 config entries.
    dev_registry = await hass.helpers.device_registry.async_get_registry()
    identifiers = {("serial_number", MOCK_SERIAL_NUMBER)}
    dev_registry.async_get_or_create(
        config_entry_id=v1_entry.entry_id,
        identifiers=identifiers,
    )
    device = dev_registry.async_get_or_create(
        config_entry_id=v2_entry.entry_id,
        identifiers=identifiers,
    )
    assert len(device.config_entries) == 2

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(v2_entry.entry_id)
    await hass.async_block_till_done()

    # Expect the v1 config entry was removed.
    config_entries = hass.config_entries.async_entries()
    assert len(config_entries) == 1
    assert config_entries[0].entry_id == v2_entry.entry_id


async def test_get_wemo_device_bad_port(hass):
    """Test that setup fails when pywemo cannot find the device's port."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: MOCK_HOST, CONF_PORT: MOCK_PORT, CONF_DOMAIN: SWITCH_DOMAIN},
        title=MOCK_NAME,
        unique_id=MOCK_SERIAL_NUMBER,
        version=CONFIG_ENTRY_VERSION,
    )
    config_entry.add_to_hass(hass)
    with patch("pywemo.setup_url_for_address", return_value=None):
        assert await hass.config_entries.async_setup(config_entry.entry_id) is False


async def test_get_wemo_device_failed_connection(hass):
    """Test that setup fails when pywemo cannot connect to the device."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: MOCK_HOST, CONF_PORT: MOCK_PORT, CONF_DOMAIN: SWITCH_DOMAIN},
        title=MOCK_NAME,
        unique_id=MOCK_SERIAL_NUMBER,
        version=CONFIG_ENTRY_VERSION,
    )
    config_entry.add_to_hass(hass)
    url = f"http://{MOCK_HOST}:{MOCK_PORT}/setup.xml"
    with patch("pywemo.setup_url_for_address", return_value=url), patch(
        "pywemo.discovery.device_from_description",
        side_effect=requests.exceptions.ConnectionError,
    ):
        assert await hass.config_entries.async_setup(config_entry.entry_id) is False
