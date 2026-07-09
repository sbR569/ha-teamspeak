"""The TeamSpeak integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import TeamSpeakCoordinator
from .services import async_setup_services, async_unload_services

PLATFORMS: list[Platform] = [Platform.SENSOR]

type TeamSpeakConfigEntry = ConfigEntry[TeamSpeakCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: TeamSpeakConfigEntry) -> bool:
    """Set up TeamSpeak from a config entry."""
    coordinator = TeamSpeakCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async_setup_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TeamSpeakConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        remaining = [
            other
            for other in hass.config_entries.async_entries(DOMAIN)
            if other.entry_id != entry.entry_id
            and other.state is ConfigEntryState.LOADED
        ]
        if not remaining:
            # Last server removed: drop the shared services too.
            async_unload_services(hass)
    return unloaded
