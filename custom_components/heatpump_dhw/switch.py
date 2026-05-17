"""Mode-toggle switch entities for Heat Pump DHW."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import DHWCoordinator
from .entity import DHWEntity


@dataclass(frozen=True)
class DHWSwitchDescription(SwitchEntityDescription):
    attr: str = ""  # attribute name on coordinator


SWITCHES: tuple[DHWSwitchDescription, ...] = (
    DHWSwitchDescription(
        key="solar_mode",
        name="Zonne-energie modus",
        icon="mdi:solar-power",
        attr="solar_mode_enabled",
    ),
    DHWSwitchDescription(
        key="price_mode",
        name="Dynamische prijs modus",
        icon="mdi:currency-eur",
        attr="price_mode_enabled",
    ),
    DHWSwitchDescription(
        key="boost_mode",
        name="Boost modus",
        icon="mdi:rocket-launch",
        attr="boost_mode_enabled",
    ),
    DHWSwitchDescription(
        key="legionella_mode",
        name="Legionella preventie",
        icon="mdi:bacteria",
        attr="legionella_mode_enabled",
    ),
    DHWSwitchDescription(
        key="vacation_mode",
        name="Vakantie modus",
        icon="mdi:beach",
        attr="vacation_mode_enabled",
    ),
    DHWSwitchDescription(
        key="on_vacation",
        name="Op vakantie",
        icon="mdi:airplane-takeoff",
        attr="vacation_active",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DHWCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(DHWSwitch(coordinator, desc) for desc in SWITCHES)


class DHWSwitch(DHWEntity, SwitchEntity):
    """Toggle switch that flips a mode flag on the coordinator."""

    entity_description: DHWSwitchDescription

    def __init__(self, coordinator: DHWCoordinator, description: DHWSwitchDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._attr_name = description.name

    @property
    def is_on(self) -> bool:
        return bool(getattr(self.coordinator, self.entity_description.attr, False))

    async def async_turn_on(self, **kwargs: Any) -> None:
        setattr(self.coordinator, self.entity_description.attr, True)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        setattr(self.coordinator, self.entity_description.attr, False)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
