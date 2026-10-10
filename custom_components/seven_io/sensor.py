"""Guthaben, Status des RCS-Agents und letzte Webhook-Zustellung."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    AGENT_STATES,
    CONF_EVENT_TYPES,
    CONF_RCS_AGENT,
    CONF_WEBHOOK_MODE,
    SIGNAL_WEBHOOK,
)
from .entity import geraet


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    daten = entry.runtime_data
    entities: list[SensorEntity] = [GuthabenSensor(daten["guthaben"], entry)]
    if entry.options.get(CONF_RCS_AGENT):
        entities.append(AgentSensor(daten["agents"], entry))
    if daten["ziel_url"]:
        entities.append(WebhookSensor(entry))
    async_add_entities(entities)


class GuthabenSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "guthaben"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_guthaben"
        self._attr_device_info = geraet(entry)

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data["betrag"]

    @property
    def native_unit_of_measurement(self) -> str:
        return self.coordinator.data["waehrung"]


class AgentSensor(CoordinatorEntity, SensorEntity):
    """Status des gewählten RCS-Agents: test, pending, launched (bzw. wait/approved/denied)."""

    _attr_has_entity_name = True
    _attr_translation_key = "rcs_agent"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = AGENT_STATES

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_rcs_agent"
        self._attr_device_info = geraet(entry)
        self._agent_id = entry.options[CONF_RCS_AGENT]

    @property
    def native_value(self) -> str:
        agent = self.coordinator.data["gewaehlt"] or {}
        status = agent.get("status")
        return status if status in AGENT_STATES else "unbekannt"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        agent = self.coordinator.data["gewaehlt"] or {}
        return {
            "agent_id": self._agent_id,
            "display_name": agent.get("display_name"),
            "generic": agent.get("is_generic"),
            "created": agent.get("created"),
            "logo_url": agent.get("logo_url"),
        }


class WebhookSensor(SensorEntity):
    """Zeitpunkt der letzten angenommenen Zustellung — zum Prüfen, ob Webhooks ankommen."""

    _attr_has_entity_name = True
    _attr_translation_key = "letzter_webhook"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_letzter_webhook"
        self._attr_device_info = geraet(entry)

    async def async_added_to_hass(self) -> None:
        @callback
        def _neu(entry_id: str) -> None:
            if entry_id == self._entry.entry_id:
                self.async_write_ha_state()

        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_WEBHOOK, _neu))

    @property
    def native_value(self) -> datetime | None:
        return self._entry.runtime_data["webhook"]["letzter"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        status = self._entry.runtime_data["webhook"]
        return {
            "count": status["anzahl"],
            "last_event_type": status["letzter_typ"],
            "mode": self._entry.options.get(CONF_WEBHOOK_MODE),
            "event_types": self._entry.options.get(CONF_EVENT_TYPES),
        }
