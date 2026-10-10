"""Event-Entity "Eingehende Nachricht" — Auslöser im Automationseditor.

Feuert bei jeder angenommenen eingehenden Nachricht (nach der Absender-Freigabe).
Event-Typ ist der content_type (text, suggestion_response, location, user_file);
die Attribute entsprechen dem Bus-Event seven_io_message_received ohne ``raw``.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import NACHRICHT_TYPEN, SIGNAL_NACHRICHT
from .entity import geraet


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    if entry.runtime_data["ziel_url"]:
        async_add_entities([NachrichtEvent(entry)])


class NachrichtEvent(EventEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "nachricht"
    _attr_event_types = NACHRICHT_TYPEN

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry_id = entry.entry_id
        self._attr_unique_id = f"{entry.entry_id}_nachricht"
        self._attr_device_info = geraet(entry)

    async def async_added_to_hass(self) -> None:
        @callback
        def _neu(entry_id: str, daten: dict[str, Any]) -> None:
            if entry_id != self._entry_id:
                return
            typ = daten.get("content_type")
            self._trigger_event(
                typ if typ in NACHRICHT_TYPEN else "other",
                {k: v for k, v in daten.items() if k != "raw" and v is not None},
            )
            self.async_write_ha_state()

        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_NACHRICHT, _neu))
