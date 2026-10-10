"""Einrichtung und Optionen."""
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.seven_io.const import DOMAIN

API = "https://gateway.seven.io/api/"
AGENTS = {"agents": [
    {"id": "gen", "display_name": "seven", "status": "approved", "is_generic": True},
    {"id": "ag1", "display_name": "Casa", "status": "test", "is_generic": False},
]}


def _konto(aioclient_mock, guthaben=None):
    aioclient_mock.get(API + "balance", json=guthaben or {"amount": 12.5, "currency": "EUR"})
    aioclient_mock.get(API + "rcs/agents", json=AGENTS)


async def _bis_webhook(hass, aioclient_mock):
    _konto(aioclient_mock)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"api_key": " key "})
    assert result["step_id"] == "settings"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"rcs_agent": "ag1", "sms_sender": "CasaSchmid", "signing_secret": "s"}
    )
    assert result["type"] is FlowResultType.MENU
    return result


async def test_eigene_url(hass, aioclient_mock):
    result = await _bis_webhook(hass, aioclient_mock)
    # ohne Nabu-Casa-Login wird der Cloudhook nicht angeboten
    assert result["menu_options"] == ["custom_url", "none"]
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "custom_url"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"base_url": "http://ha.example.de", "event_types": ["rcs"]}
    )
    assert result["errors"] == {"base_url": "url_not_https"}
    with patch("custom_components.seven_io.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"base_url": "https://ha.example.de/", "event_types": ["rcs", "dlr"]}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "seven.io Casa"
    assert result["data"]["api_key"] == "key" and len(result["data"]["webhook_id"]) == 64
    assert result["options"] == {
        "rcs_agent": "ag1", "sms_sender": "CasaSchmid", "signing_secret": "s",
        "webhook_mode": "custom_url", "event_types": ["rcs", "dlr"], "base_url": "https://ha.example.de",
    }


async def test_ohne_webhook(hass, aioclient_mock):
    result = await _bis_webhook(hass, aioclient_mock)
    with patch("custom_components.seven_io.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "none"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"]["webhook_mode"] == "none"


async def test_nabu_casa(hass, aioclient_mock):
    with patch("custom_components.seven_io.cloudhook.angemeldet", return_value=True):
        result = await _bis_webhook(hass, aioclient_mock)
    assert result["menu_options"] == ["nabu_casa", "custom_url", "none"]
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "nabu_casa"})
    with patch("custom_components.seven_io.cloudhook.abo_aktiv", return_value=True), \
         patch("custom_components.seven_io.cloudhook.verbunden", return_value=False):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"event_types": ["rcs"]})
    assert result["errors"] == {"base": "cloud_not_connected"}
    with patch("custom_components.seven_io.cloudhook.abo_aktiv", return_value=True), \
         patch("custom_components.seven_io.cloudhook.verbunden", return_value=True), \
         patch("custom_components.seven_io.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"event_types": ["rcs"]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"]["webhook_mode"] == "nabu_casa" and result["options"]["base_url"] is None


async def test_falscher_key_und_absender(hass, aioclient_mock):
    aioclient_mock.get(API + "balance", text="900")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"api_key": "falsch"})
    assert result["errors"] == {"base": "invalid_auth"}

    aioclient_mock.clear_requests()
    _konto(aioclient_mock)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"api_key": "key"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"sms_sender": "Viel zu langer Absender"}
    )
    assert result["errors"] == {"sms_sender": "sender_invalid"}


async def test_doppelter_key(hass, aioclient_mock):
    MockConfigEntry(domain=DOMAIN, data={"api_key": "key", "webhook_id": "x"}).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"api_key": "key"})
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"
