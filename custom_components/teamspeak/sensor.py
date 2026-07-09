"""Sensors for the TeamSpeak integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import CONF_HOST, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TeamSpeakConfigEntry
from .const import DOMAIN
from .coordinator import TeamSpeakCoordinator, TeamSpeakData


@dataclass(frozen=True, kw_only=True)
class TeamSpeakSensorDescription(SensorEntityDescription):
    """Describes a TeamSpeak sensor."""

    value_fn: Callable[[TeamSpeakData], StateType | datetime]
    attributes_fn: Callable[[TeamSpeakData], dict[str, Any]] | None = None


def _client_names_state(data: TeamSpeakData) -> str:
    """Join the client names for display; HA states are capped at 255 chars."""
    if not data.client_names:
        return "—"
    joined = ", ".join(data.client_names)
    if len(joined) > 255:
        joined = joined[:252] + "…"
    return joined


def _real_channel_count(data: TeamSpeakData) -> int:
    """Number of channels that are not spacers."""
    return sum(1 for channel in data.channels if not channel["is_spacer"])


SENSORS: tuple[TeamSpeakSensorDescription, ...] = (
    TeamSpeakSensorDescription(
        key="status",
        translation_key="status",
        icon="mdi:server",
        value_fn=lambda data: data.status,
    ),
    TeamSpeakSensorDescription(
        key="online_since",
        translation_key="online_since",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.online_since,
    ),
    TeamSpeakSensorDescription(
        key="version",
        translation_key="version",
        icon="mdi:information-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.version,
    ),
    TeamSpeakSensorDescription(
        key="max_clients",
        translation_key="max_clients",
        icon="mdi:account-group-outline",
        value_fn=lambda data: data.max_clients,
    ),
    TeamSpeakSensorDescription(
        key="clients_online",
        translation_key="clients_online",
        icon="mdi:account-voice",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.clients_online,
        # 'clients' carries the full per-client detail (channel, country,
        # platform, idle, mute flags, groups...) for a dashboard/custom card.
        attributes_fn=lambda data: {
            "client_names": data.client_names,
            "clients": data.clients,
            "query_clients": data.query_clients,
        },
    ),
    TeamSpeakSensorDescription(
        key="client_names",
        translation_key="client_names",
        icon="mdi:account-multiple-outline",
        value_fn=_client_names_state,
        attributes_fn=lambda data: {"client_names": data.client_names},
    ),
    TeamSpeakSensorDescription(
        key="channels",
        translation_key="channels",
        icon="mdi:format-list-bulleted-type",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_real_channel_count,
        # 'channels' is the full tree (cid/parent_id/order + metadata); a card
        # combines it with the clients' 'cid' to render the channel viewer.
        attributes_fn=lambda data: {"channels": data.channels},
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TeamSpeakConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the TeamSpeak sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        TeamSpeakSensor(coordinator, entry, description) for description in SENSORS
    )


class TeamSpeakSensor(CoordinatorEntity[TeamSpeakCoordinator], SensorEntity):
    """A sensor exposing one value of the TeamSpeak server."""

    _attr_has_entity_name = True
    entity_description: TeamSpeakSensorDescription

    def __init__(
        self,
        coordinator: TeamSpeakCoordinator,
        entry: TeamSpeakConfigEntry,
        description: TeamSpeakSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"TeamSpeak {entry.data[CONF_HOST]}",
            manufacturer="TeamSpeak Systems GmbH",
            model="TeamSpeak Server",
            sw_version=coordinator.data.version if coordinator.data else None,
        )

    @property
    def native_value(self) -> StateType | datetime:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes (e.g. the list of client names)."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator.data)
