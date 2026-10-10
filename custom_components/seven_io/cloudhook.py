"""Zugriff auf Nabu-Casa-Cloudhooks.

Die cloud-Komponente wird erst importiert, wenn sie in Home Assistant geladen ist:
ihr Import zieht Assist, TTS und Kamera nach und würde sonst ohne Cloud-Nutzung
blockierend im Event-Loop laden.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant


class CloudhookFehler(Exception):
    """Cloud nicht angemeldet, nicht verbunden oder ohne Abo."""


def _cloud(hass: HomeAssistant):
    if "cloud" not in hass.config.components:
        return None
    from homeassistant.components import cloud

    return cloud


def angemeldet(hass: HomeAssistant) -> bool:
    cloud = _cloud(hass)
    return bool(cloud and cloud.async_is_logged_in(hass))


def abo_aktiv(hass: HomeAssistant) -> bool:
    cloud = _cloud(hass)
    return bool(cloud and cloud.async_active_subscription(hass))


def verbunden(hass: HomeAssistant) -> bool:
    cloud = _cloud(hass)
    return bool(cloud and cloud.async_is_connected(hass))


async def url_holen(hass: HomeAssistant, webhook_id: str) -> str:
    """Vorhandenen Cloudhook liefern oder anlegen."""
    cloud = _cloud(hass)
    if cloud is None:
        raise CloudhookFehler("Home Assistant Cloud ist nicht eingerichtet")
    try:
        return await cloud.async_get_or_create_cloudhook(hass, webhook_id)
    except cloud.CloudNotAvailable as err:
        raise CloudhookFehler(str(err) or type(err).__name__) from err


async def loeschen(hass: HomeAssistant, webhook_id: str) -> None:
    cloud = _cloud(hass)
    if cloud is None:
        return
    try:
        await cloud.async_delete_cloudhook(hass, webhook_id)
    except cloud.CloudNotAvailable:
        pass
