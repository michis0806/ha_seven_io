"""Diagnose-Download: Einstellungen, Agents und eigene Webhooks, ohne Geheimnisse."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

from .const import CONF_SIGNING_SECRET, CONF_WEBHOOK_ID

GEHEIM = {CONF_API_KEY, CONF_SIGNING_SECRET, CONF_WEBHOOK_ID, "ziel_url", "target_url", "headers"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    daten = entry.runtime_data
    hooks = await daten["api"].hooks()
    return async_redact_data(
        {
            "data": dict(entry.data),
            "options": dict(entry.options),
            "ziel_url": daten["ziel_url"],
            "guthaben": daten["guthaben"].data,
            "agents": daten["agents"].data,
            "webhook": {**daten["webhook"], "letzter": str(daten["webhook"]["letzter"])},
            # Alle Webhooks des Kontos, damit fremde von eigenen unterscheidbar sind
            "hooks": hooks,
        },
        GEHEIM,
    )
