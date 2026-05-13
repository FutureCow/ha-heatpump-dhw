"""Base entity for Heat Pump DHW."""
from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DHWCoordinator


class DHWEntity(CoordinatorEntity[DHWCoordinator]):
    """Base entity that holds a reference to the DHW coordinator."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DHWCoordinator, unique_suffix: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{unique_suffix}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": coordinator.entry.title,
            "manufacturer": "Heat Pump DHW",
            "model": "Smart DHW Controller",
        }
