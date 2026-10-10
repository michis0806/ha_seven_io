"""Config-Flow für seven.io.

Ablauf: API-Key (geprüft über /balance und /rcs/agents) -> RCS-Agent,
SMS-Absender und Signing Secret -> Webhook wählen (Nabu Casa, eigene URL oder
keiner). Die Optionen durchlaufen dieselben Schritte ab den Einstellungen; die
Webhooks bei seven.io gleicht das Setup nach dem Neuladen selbst ab.
"""
from __future__ import annotations

import secrets
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import cloudhook
from .api import SevenApi, SevenAuthError, SevenError
from .const import (
    CONF_BASE_URL,
    CONF_EVENT_TYPES,
    CONF_RCS_AGENT,
    CONF_SIGNING_SECRET,
    CONF_SMS_SENDER,
    CONF_WEBHOOK_ID,
    CONF_WEBHOOK_MODE,
    DEFAULT_EVENT_TYPES,
    DOMAIN,
    EVENT_TYPES,
    WEBHOOK_CUSTOM_URL,
    WEBHOOK_NABU_CASA,
    WEBHOOK_NONE,
)

PASSWORT = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
EVENT_AUSWAHL = SelectSelector(
    SelectSelectorConfig(
        options=list(EVENT_TYPES),
        multiple=True,
        mode=SelectSelectorMode.LIST,
        translation_key=CONF_EVENT_TYPES,
    )
)


async def _pruefen(hass: HomeAssistant, api_key: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """API-Key prüfen; liefert die RCS-Agents oder Fehler fürs Formular."""
    api = SevenApi(async_get_clientsession(hass), api_key)
    try:
        await api.guthaben()
        return await api.agents(), {}
    except SevenAuthError:
        return [], {"base": "invalid_auth"}
    except SevenError:
        return [], {"base": "cannot_connect"}


def _einstellungen_schema(agents: list[dict[str, Any]]) -> vol.Schema:
    felder: dict[Any, Any] = {}
    if agents:
        felder[vol.Optional(CONF_RCS_AGENT)] = SelectSelector(
            SelectSelectorConfig(
                options=[
                    SelectOptionDict(
                        value=a["id"],
                        label=f"{a.get('display_name') or a['id']} ({a.get('status', '?')})",
                    )
                    for a in agents
                ],
                mode=SelectSelectorMode.DROPDOWN,
            )
        )
    felder[vol.Optional(CONF_SMS_SENDER)] = str
    felder[vol.Optional(CONF_SIGNING_SECRET)] = PASSWORT
    return vol.Schema(felder)


def _absender_gueltig(absender: str) -> bool:
    """seven.io: bis 11 Zeichen alphanumerisch oder bis 16 Ziffern."""
    if absender.lstrip("+").isdigit():
        return len(absender.lstrip("+")) <= 16
    return len(absender) <= 11 and absender.isascii() and absender.replace(" ", "").isalnum()


class _Schritte:
    """Einstellungs- und Webhook-Schritte, gemeinsam für Einrichtung und Optionen."""

    hass: HomeAssistant
    _agents: list[dict[str, Any]]
    _optionen: dict[str, Any]

    async def _fertig(self) -> ConfigFlowResult:
        raise NotImplementedError

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            werte = {
                key: (user_input.get(key) or "").strip() or None
                for key in (CONF_RCS_AGENT, CONF_SMS_SENDER, CONF_SIGNING_SECRET)
            }
            if werte[CONF_SMS_SENDER] and not _absender_gueltig(werte[CONF_SMS_SENDER]):
                errors[CONF_SMS_SENDER] = "sender_invalid"
            else:
                self._optionen.update(werte)
                return await self.async_step_webhook()
        vorschlag = {**self._optionen, **(user_input or {})}
        if self._agents and not vorschlag.get(CONF_RCS_AGENT):
            # Eigener Agent vor generischem, sonst der erste
            eigene = [a for a in self._agents if not a.get("is_generic")]
            vorschlag[CONF_RCS_AGENT] = (eigene or self._agents)[0]["id"]
        return self.async_show_form(
            step_id="settings",
            data_schema=self.add_suggested_values_to_schema(
                _einstellungen_schema(self._agents), vorschlag
            ),
            errors=errors,
        )

    async def async_step_webhook(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        wege = [WEBHOOK_CUSTOM_URL, WEBHOOK_NONE]
        if cloudhook.angemeldet(self.hass):
            wege.insert(0, WEBHOOK_NABU_CASA)
        return self.async_show_menu(step_id="webhook", menu_options=wege)

    async def async_step_nabu_casa(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not cloudhook.abo_aktiv(self.hass):
                errors["base"] = "cloud_no_subscription"
            elif not cloudhook.verbunden(self.hass):
                errors["base"] = "cloud_not_connected"
            elif not user_input.get(CONF_EVENT_TYPES):
                errors[CONF_EVENT_TYPES] = "no_event_types"
            else:
                self._optionen.update(
                    {
                        CONF_WEBHOOK_MODE: WEBHOOK_NABU_CASA,
                        CONF_EVENT_TYPES: user_input[CONF_EVENT_TYPES],
                        CONF_BASE_URL: None,
                    }
                )
                return await self._fertig()
        return self.async_show_form(
            step_id="nabu_casa",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_EVENT_TYPES,
                        default=self._optionen.get(CONF_EVENT_TYPES) or DEFAULT_EVENT_TYPES,
                    ): EVENT_AUSWAHL
                }
            ),
            errors=errors,
        )

    async def async_step_custom_url(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_BASE_URL].strip().rstrip("/")
            if not url.startswith("https://"):
                errors[CONF_BASE_URL] = "url_not_https"
            elif not user_input.get(CONF_EVENT_TYPES):
                errors[CONF_EVENT_TYPES] = "no_event_types"
            else:
                self._optionen.update(
                    {
                        CONF_WEBHOOK_MODE: WEBHOOK_CUSTOM_URL,
                        CONF_EVENT_TYPES: user_input[CONF_EVENT_TYPES],
                        CONF_BASE_URL: url,
                    }
                )
                return await self._fertig()
        vorgabe = self._optionen.get(CONF_BASE_URL) or self.hass.config.external_url or ""
        schema = vol.Schema(
            {
                vol.Required(CONF_BASE_URL, default=vorgabe): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.URL)
                ),
                vol.Required(
                    CONF_EVENT_TYPES,
                    default=self._optionen.get(CONF_EVENT_TYPES) or DEFAULT_EVENT_TYPES,
                ): EVENT_AUSWAHL,
            }
        )
        return self.async_show_form(step_id="custom_url", data_schema=schema, errors=errors)

    async def async_step_none(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._optionen.update(
            {CONF_WEBHOOK_MODE: WEBHOOK_NONE, CONF_EVENT_TYPES: [], CONF_BASE_URL: None}
        )
        return await self._fertig()


class SevenConfigFlow(_Schritte, ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._api_key = ""
        self._agents = []
        self._optionen = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SevenOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            self._async_abort_entries_match({CONF_API_KEY: api_key})
            self._agents, errors = await _pruefen(self.hass, api_key)
            if not errors:
                self._api_key = api_key
                return await self.async_step_settings()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): PASSWORT}),
            errors=errors,
        )

    async def _fertig(self) -> ConfigFlowResult:
        agent = next(
            (a for a in self._agents if a.get("id") == self._optionen.get(CONF_RCS_AGENT)), None
        )
        titel = f"seven.io {agent.get('display_name') or agent['id']}" if agent else "seven.io"
        return self.async_create_entry(
            title=titel,
            data={CONF_API_KEY: self._api_key, CONF_WEBHOOK_ID: secrets.token_hex(32)},
            options=self._optionen,
        )

    # --------------------------------------------------------------- Reauth

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            _, errors = await _pruefen(self.hass, api_key)
            if not errors:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(), data_updates={CONF_API_KEY: api_key}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): PASSWORT}),
            errors=errors,
        )


class SevenOptionsFlow(_Schritte, OptionsFlow):
    """Agent, Absender, Signing Secret und Webhook nachträglich ändern."""

    def __init__(self) -> None:
        self._agents = []
        self._optionen = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._optionen = dict(self.config_entry.options)
        laufend = getattr(self.config_entry, "runtime_data", None)
        if laufend and laufend["agents"].data:
            self._agents = laufend["agents"].data["agents"]
        else:
            self._agents, _ = await _pruefen(self.hass, self.config_entry.data[CONF_API_KEY])
        return await self.async_step_settings()

    async def _fertig(self) -> ConfigFlowResult:
        return self.async_create_entry(data=self._optionen)
