"""Button entities for Heat Pump DHW."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import DHWCoordinator
from .entity import DHWEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DHWCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DHWManualHeatButton(coordinator)])


class DHWManualHeatButton(DHWEntity, ButtonEntity):
    """Knop om de warmtepomp handmatig te starten tot doeltemperatuur bereikt is."""

    def __init__(self, coordinator: DHWCoordinator) -> None:
        super().__init__(coordinator, "manual_heat")
        self._attr_name = "Zet aan"
        self._attr_icon = "mdi:water-boiler"

    async def async_press(self) -> None:
        self.coordinator._manual_heat = True
        await self.coordinator.async_request_refresh()
