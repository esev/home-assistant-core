"""Tests for the Wemo config flow module."""

import pytest
import requests
import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.components import ssdp
from homeassistant.components.wemo.config_flow import (
    ERROR_CANNOT_CONNECT,
    ERROR_CANNOT_DETERMINE_PORT,
    REASON_NO_DEVICES_FOUND,
    STEP_ID_CONFIRM,
    STEP_ID_USER,
)
from homeassistant.components.wemo.const import DOMAIN
from homeassistant.config_entries import (
    SOURCE_IGNORE,
    SOURCE_IMPORT,
    SOURCE_SSDP,
    SOURCE_UNIGNORE,
    SOURCE_USER,
)
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SOURCE, CONF_UNIQUE_ID

from .conftest import MOCK_HOST, MOCK_NAME, MOCK_PORT, MOCK_SERIAL_NUMBER

from tests.async_mock import patch
from tests.common import MockConfigEntry, mock_device_registry

MOCK_DISCOVERY_INFO = {
    ssdp.ATTR_UPNP_MANUFACTURER: "Belkin International Inc.",
    ssdp.ATTR_UPNP_FRIENDLY_NAME: "Wemo Switch",
    ssdp.ATTR_UPNP_SERIAL: MOCK_SERIAL_NUMBER,
    ssdp.ATTR_SSDP_LOCATION: f"http://{MOCK_HOST}:{MOCK_PORT}/setup.xml",
}

MOCK_FLOW_DATA = {
    CONF_HOST: MOCK_HOST,
    CONF_PORT: MOCK_PORT,
}


async def test_ssdp(hass, pywemo_device):
    """Test a ssdp discovery flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={CONF_SOURCE: SOURCE_SSDP},
        data=MOCK_DISCOVERY_INFO,
    )
    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["step_id"] == STEP_ID_CONFIRM

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == data_entry_flow.RESULT_TYPE_CREATE_ENTRY
    assert result["title"] == MOCK_NAME
    assert result["data"] == MOCK_FLOW_DATA


async def test_ssdp_unable_to_connect(hass):
    """Test that the config flow is aborted there is a connection error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={CONF_SOURCE: SOURCE_SSDP},
        data=MOCK_DISCOVERY_INFO,
    )
    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["step_id"] == STEP_ID_CONFIRM

    url = f"http://{MOCK_HOST}:{MOCK_PORT}/setup.xml"
    with patch("pywemo.setup_url_for_address", return_value=url), patch(
        "pywemo.discovery.device_from_description",
        side_effect=requests.exceptions.ConnectionError,
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["errors"] == {"base": ERROR_CANNOT_CONNECT}


async def test_ssdp_config_entry_created_when_v1_device_exists(hass, pywemo_device):
    """Create the config entry with no user prompt when the device already exists.

    To ease converting from v1 config flow to v2, any devices that already exist
    in the device registry do not need confirmation from the user before adding the
    v2 config flow entry.
    """
    device_reg = mock_device_registry(hass)
    v1_config_entry = MockConfigEntry(
        domain=DOMAIN,
        source=SOURCE_IMPORT,
        title=MOCK_NAME,
        unique_id=DOMAIN,
    )
    v1_config_entry.add_to_hass(hass)
    assert device_reg.async_get_or_create(
        config_entry_id=v1_config_entry.entry_id,
        identifiers={(DOMAIN, MOCK_SERIAL_NUMBER)},
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={CONF_SOURCE: SOURCE_SSDP},
        data=MOCK_DISCOVERY_INFO,
    )
    assert result["type"] == data_entry_flow.RESULT_TYPE_CREATE_ENTRY
    assert result["title"] == MOCK_NAME
    assert result["data"] == MOCK_FLOW_DATA
    assert result["result"].unique_id == MOCK_SERIAL_NUMBER


async def test_ssdp_update(hass):
    """Test a ssdp import flow."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={**MOCK_FLOW_DATA, CONF_HOST: "old_host"},
        title=MOCK_NAME,
        unique_id=MOCK_SERIAL_NUMBER,
    )
    entry.add_to_hass(hass)
    assert entry.data != MOCK_FLOW_DATA

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={CONF_SOURCE: SOURCE_SSDP},
        data=MOCK_DISCOVERY_INFO,
    )
    assert result["type"] == data_entry_flow.RESULT_TYPE_ABORT
    assert result["reason"] == "already_configured"
    assert entry.data == MOCK_FLOW_DATA  # CONF_HOST should match now.


async def test_user(hass, pywemo_device):
    """Test a manual user configuration flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={CONF_SOURCE: SOURCE_USER},
        data=None,
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["step_id"] == STEP_ID_USER

    user_input = {CONF_HOST: MOCK_HOST, CONF_PORT: MOCK_PORT}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input
    )
    assert result["type"] == data_entry_flow.RESULT_TYPE_CREATE_ENTRY
    assert result["title"] == MOCK_NAME
    assert result["data"] == MOCK_FLOW_DATA
    assert result["result"].unique_id == MOCK_SERIAL_NUMBER


async def test_user_without_port(hass, pywemo_device):
    """Test a manual user configuration flow where the port is unspecified."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={CONF_SOURCE: SOURCE_USER},
        data=None,
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["step_id"] == STEP_ID_USER

    user_input = {CONF_HOST: MOCK_HOST}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input
    )
    assert result["type"] == data_entry_flow.RESULT_TYPE_CREATE_ENTRY
    assert result["title"] == MOCK_NAME
    assert result["data"] == {
        CONF_HOST: MOCK_HOST,
        CONF_PORT: 0,
    }
    assert result["result"].unique_id == MOCK_SERIAL_NUMBER


async def test_user_with_missing_required_port(hass, pywemo_device):
    """Test a manual user configuration flow when the port isn't auto determined."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={CONF_SOURCE: SOURCE_USER},
        data=None,
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["step_id"] == STEP_ID_USER

    user_input = {CONF_HOST: MOCK_HOST}

    with patch("pywemo.setup_url_for_address", return_value=None):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input
        )
    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["errors"] == {"base": ERROR_CANNOT_DETERMINE_PORT}

    # Expected to fail because CONF_PORT is a required field.
    with pytest.raises(vol.error.MultipleInvalid):
        await hass.config_entries.flow.async_configure(result["flow_id"], user_input)

    # Completes successfully when the port is specified.
    user_input = {CONF_HOST: MOCK_HOST, CONF_PORT: MOCK_PORT}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input
    )
    assert result["type"] == data_entry_flow.RESULT_TYPE_CREATE_ENTRY


async def test_ignore_and_unignore(hass, pywemo_device):
    """Test a user ignoring and then un-ignoring a discovered device."""
    # Discovery.
    ssdp_result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={CONF_SOURCE: SOURCE_SSDP},
        data=MOCK_DISCOVERY_INFO,
    )
    assert ssdp_result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert ssdp_result["step_id"] == STEP_ID_CONFIRM

    # User ignores the discovered entry.
    ignore_result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={CONF_SOURCE: SOURCE_IGNORE},
        data={CONF_UNIQUE_ID: MOCK_SERIAL_NUMBER},
    )
    assert ignore_result["type"] == data_entry_flow.RESULT_TYPE_CREATE_ENTRY
    assert ignore_result["result"].source == SOURCE_IGNORE

    # User un-ignores the discovered entry.
    await hass.config_entries.async_remove(ignore_result["result"].entry_id)
    await hass.async_block_till_done()

    # Check that the flow is back at the confirm step.
    flow_entry = hass.config_entries.flow.async_progress()[0]
    assert flow_entry["step_id"] == STEP_ID_CONFIRM
    assert flow_entry["context"]["user_input"] == MOCK_FLOW_DATA


async def test_unignore_with_no_previous_discovery(hass):
    """Unignore fails if the device was not previously discovered."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={CONF_SOURCE: SOURCE_UNIGNORE},
        data={CONF_UNIQUE_ID: MOCK_SERIAL_NUMBER},
    )
    assert result["type"] == data_entry_flow.RESULT_TYPE_ABORT
    assert result["reason"] == REASON_NO_DEVICES_FOUND
