"""Binary sensor for the TeamSpeak integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TeamSpeakConfigEntry
from .const import DOMAIN
from .coordinator import TeamSpeakCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TeamSpeakConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the TeamSpeak binary sensor."""
    async_add_entities([TeamSpeakOnlineSensor(entry.runtime_data, entry)])


class TeamSpeakOnlineSensor(
    CoordinatorEntity[TeamSpeakCoordinator], BinarySensorEntity
):
    """Connectivity sensor: on while the virtual server reports 'online'."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "online"

    def __init__(
        self, coordinator: TeamSpeakCoordinator, entry: TeamSpeakConfigEntry
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_online"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"TeamSpeak {entry.data[CONF_HOST]}",
            manufacturer="TeamSpeak Systems GmbH",
            model="TeamSpeak Server",
        )

    @property
    def is_on(self) -> bool:
        """Return True while the server is online."""
        return self.coordinator.data.status == "online"
