"""Sensor entities for Heat Pump DHW."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    CURRENCY_EURO,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import DHWCoordinator
from .entity import DHWEntity


@dataclass(frozen=True)
class DHWSensorDescription(SensorEntityDescription):
    data_key: str = ""


SENSORS: tuple[DHWSensorDescription, ...] = (
    DHWSensorDescription(
        key="boiler_temp",
        data_key="boiler_temp",
        name="Boiler temperatuur",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer-water",
    ),
    DHWSensorDescription(
        key="active_mode",
        data_key="active_mode",
        name="Actieve modus",
        icon="mdi:water-boiler",
    ),
    DHWSensorDescription(
        key="status_text",
        data_key="status_text",
        name="Status",
        icon="mdi:information-outline",
    ),
    DHWSensorDescription(
        key="session_kwh",
        data_key="session_kwh",
        name="Sessie energie",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:lightning-bolt",
    ),
    DHWSensorDescription(
        key="session_cost",
        data_key="session_cost",
        name="Sessie kosten",
        native_unit_of_measurement=CURRENCY_EURO,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:currency-eur",
    ),
    DHWSensorDescription(
        key="session_savings",
        data_key="session_savings",
        name="Sessie besparing",
        native_unit_of_measurement=CURRENCY_EURO,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:piggy-bank-outline",
    ),
    DHWSensorDescription(
        key="monthly_savings",
        data_key="monthly_savings",
        name="Maandelijkse besparing",
        native_unit_of_measurement=CURRENCY_EURO,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:piggy-bank",
    ),
    DHWSensorDescription(
        key="heat_up_duration_min",
        data_key="heat_up_duration_min",
        name="Opwarmtijd (gemiddeld)",
        native_unit_of_measurement="min",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:timer-outline",
    ),
    DHWSensorDescription(
        key="next_heating",
        data_key="next_heating",
        name="Volgende verwarming",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:calendar-clock",
    ),
    DHWSensorDescription(
        key="power_w",
        data_key="power_w",
        name="Huidig vermogen",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:flash",
    ),
    DHWSensorDescription(
        key="outside_temp",
        data_key="outside_temp",
        name="Buitentemperatuur",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer",
    ),
    DHWSensorDescription(
        key="session_cop",
        data_key="session_cop",
        name="Sessie COP",
        native_unit_of_measurement=None,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:heat-pump",
    ),
    DHWSensorDescription(
        key="avg_cop",
        data_key="avg_cop",
        name="Gemiddelde COP",
        native_unit_of_measurement=None,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-line",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DHWCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(DHWSensor(coordinator, desc) for desc in SENSORS)


class DHWSensor(DHWEntity, SensorEntity):
    """A sensor that reads from the coordinator data dict."""

    entity_description: DHWSensorDescription

    def __init__(self, coordinator: DHWCoordinator, description: DHWSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._attr_name = description.name

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        value = self.coordinator.data.get(self.entity_description.data_key)
        if value is None:
            return None
        # Timestamp sensors: return datetime object if possible
        if self.entity_description.device_class == SensorDeviceClass.TIMESTAMP and isinstance(value, str):
            from homeassistant.util import dt as dt_util
            return dt_util.parse_datetime(value)
        return value
