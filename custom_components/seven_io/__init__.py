"""seven.io — SMS und RCS über seven.io, eingehende RCS-Nachrichten als Events.

Einrichtung mit API-Key und Webhook (Nabu Casa, eigene URL oder keiner),
Guthaben und RCS-Agent-Status als Sensoren, eingehende Nachrichten und
Statusmeldungen als Events, Versand über die Aktion seven_io.send_message.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import cloudhook, webhook as wh
from .services import async_setup_services
from .api import SevenApi, SevenAuthError, SevenError
from .const import (
    AGENTS_INTERVAL,
    BALANCE_INTERVAL,
    CONF_RCS_AGENT,
    CONF_WEBHOOK_ID,
    DOMAIN,
    EVENT_AGENT_STATUS_CHANGED,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_setup_services(hass)
    return True


def _speicher(hass: HomeAssistant, entry: ConfigEntry) -> Store[dict[str, Any]]:
    return Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    api = SevenApi(async_get_clientsession(hass), entry.data[CONF_API_KEY])
    guthaben = GuthabenCoordinator(hass, entry, api)
    agents = AgentsCoordinator(hass, entry, api)
    await guthaben.async_config_entry_first_refresh()
    await agents.async_config_entry_first_refresh()

    # Webhooks: öffentliche URL ermitteln, bei seven.io abgleichen, Empfang öffnen
    store = _speicher(hass, entry)
    speicher = await store.async_load() or {"hooks": {}, "cloudhook_url": None}
    ziel_url = await wh.ziel_url_ermitteln(hass, entry, speicher)
    try:
        speicher["hooks"] = await wh.hooks_abgleichen(
            api, speicher["hooks"], ziel_url, wh.gewuenschte_typen(entry)
        )
    except SevenAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except SevenError as err:
        raise ConfigEntryNotReady(f"Webhooks nicht abgeglichen: {err}") from err
    finally:
        await store.async_save(speicher)

    entry.runtime_data = {
        "api": api,
        "guthaben": guthaben,
        "agents": agents,
        "ziel_url": ziel_url,
        "webhook": {"letzter": None, "anzahl": 0, "letzter_typ": None},
    }
    if ziel_url:
        wh.empfang_registrieren(hass, entry, ziel_url)

    entry.async_on_unload(entry.add_update_listener(_optionen_geaendert))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _optionen_geaendert(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Beim Löschen die eigenen Webhooks bei seven.io und den Cloudhook entfernen."""
    store = _speicher(hass, entry)
    speicher = await store.async_load() or {}
    api = SevenApi(async_get_clientsession(hass), entry.data[CONF_API_KEY])
    for hook_id in speicher.get("hooks", {}):
        try:
            await api.hook_loeschen(hook_id)
        except SevenError as err:
            _LOGGER.warning("Webhook %s bei seven.io nicht gelöscht: %s", hook_id, err)
    if speicher.get("cloudhook_url"):
        await cloudhook.loeschen(hass, entry.data[CONF_WEBHOOK_ID])
    await store.async_remove()
    for art in ("agent_missing", "agent_denied"):
        ir.async_delete_issue(hass, DOMAIN, f"agent_{entry.entry_id}_{art}")


class _Basis(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, api: SevenApi, name: str, minuten: int
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{name}",
            update_interval=timedelta(minutes=minuten),
        )
        self.api = api

    async def _abrufen(self) -> dict[str, Any]:
        raise NotImplementedError

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self._abrufen()
        except SevenAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except SevenError as err:
            raise UpdateFailed(str(err)) from err


class GuthabenCoordinator(_Basis):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: SevenApi) -> None:
        super().__init__(hass, entry, api, "guthaben", BALANCE_INTERVAL)

    async def _abrufen(self) -> dict[str, Any]:
        return await self.api.guthaben()


class AgentsCoordinator(_Basis):
    """RCS-Agents; meldet Statuswechsel des gewählten Agents als Event."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: SevenApi) -> None:
        super().__init__(hass, entry, api, "agents", AGENTS_INTERVAL)
        self._agent_id = entry.options.get(CONF_RCS_AGENT)

    async def _abrufen(self) -> dict[str, Any]:
        agents = await self.api.agents()
        gewaehlt = next((a for a in agents if a.get("id") == self._agent_id), None)
        vorher = (self.data or {}).get("gewaehlt")
        if vorher and gewaehlt and vorher.get("status") != gewaehlt.get("status"):
            self.hass.bus.async_fire(
                EVENT_AGENT_STATUS_CHANGED,
                {
                    "config_entry_id": self.config_entry.entry_id,
                    "agent_id": self._agent_id,
                    "from_status": vorher.get("status"),
                    "to_status": gewaehlt.get("status"),
                },
            )
        self._probleme_melden(gewaehlt)
        return {"agents": agents, "gewaehlt": gewaehlt}

    def _probleme_melden(self, gewaehlt: dict[str, Any] | None) -> None:
        """Reparaturhinweis, wenn der gewählte Agent fehlt oder abgelehnt wurde."""
        kennung = f"agent_{self.config_entry.entry_id}"
        if not self._agent_id:
            problem = None
        elif gewaehlt is None:
            problem = "agent_missing"
        elif gewaehlt.get("status") == "denied":
            problem = "agent_denied"
        else:
            problem = None
        for art in ("agent_missing", "agent_denied"):
            if art != problem:
                ir.async_delete_issue(self.hass, DOMAIN, f"{kennung}_{art}")
        if problem:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"{kennung}_{problem}",
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=problem,
                translation_placeholders={"agent": self._agent_id},
            )
