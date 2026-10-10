"""Gemeinsame Basis: ein Dienst-Gerät je seven.io-Konto."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import DOMAIN


def geraet(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="seven communications",
        model="SMS/RCS-Gateway",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url="https://app.seven.io/",
    )
