"""Number entities (configurable thresholds) for Heat Pump DHW."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DEFAULT_BOOST_TEMP,
    DEFAULT_BOOST_THRESHOLD_W,
    DEFAULT_LEGIONELLA_TEMP,
    DEFAULT_NORMAL_TEMP,
    DEFAULT_PREHEAT_TEMP,
    DEFAULT_PRICE_THRESHOLD_EUR,
    DEFAULT_SOLAR_THRESHOLD_W,
    DEFAULT_VACATION_MIN_TEMP,
    DOMAIN,
    OPT_BOOST_TEMP,
    OPT_BOOST_THRESHOLD_W,
    OPT_LEGIONELLA_TEMP,
    OPT_NORMAL_TEMP,
    OPT_PREHEAT_TEMP,
    OPT_PRICE_THRESHOLD_EUR,
    OPT_SOLAR_THRESHOLD_W,
    OPT_VACATION_MIN_TEMP,
)
from .coordinator import DHWCoordinator
from .entity import DHWEntity


@dataclass(frozen=True)
class DHWNumberDescription(NumberEntityDescription):
    options_key: str = ""
    default: float = 0.0


NUMBERS: tuple[DHWNumberDescription, ...] = (
    DHWNumberDescription(
        key="solar_threshold_w",
        options_key=OPT_SOLAR_THRESHOLD_W,
        default=DEFAULT_SOLAR_THRESHOLD_W,
        name="Zonne-overschot drempel",
        native_unit_of_measurement=UnitOfPower.WATT,
        native_min_value=0,
        native_max_value=10000,
        native_step=50,
        mode=NumberMode.BOX,
        icon="mdi:solar-power-variant",
    ),
    DHWNumberDescription(
        key="boost_threshold_w",
        options_key=OPT_BOOST_THRESHOLD_W,
        default=DEFAULT_BOOST_THRESHOLD_W,
        name="Boost overschot drempel",
        native_unit_of_measurement=UnitOfPower.WATT,
        native_min_value=0,
        native_max_value=15000,
        native_step=100,
        mode=NumberMode.BOX,
        icon="mdi:rocket-launch",
    ),
    DHWNumberDescription(
        key="price_threshold_eur",
        options_key=OPT_PRICE_THRESHOLD_EUR,
        default=DEFAULT_PRICE_THRESHOLD_EUR,
        name="Maximale prijs",
        native_unit_of_measurement="€/kWh",
        native_min_value=0,
        native_max_value=1.0,
        native_step=0.01,
        mode=NumberMode.BOX,
        icon="mdi:tag-outline",
    ),
    DHWNumberDescription(
        key="normal_temp",
        options_key=OPT_NORMAL_TEMP,
        default=DEFAULT_NORMAL_TEMP,
        name="Normale doeltemperatuur",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=35,
        native_max_value=75,
        native_step=1,
        mode=NumberMode.BOX,
        icon="mdi:thermometer",
    ),
    DHWNumberDescription(
        key="boost_temp",
        options_key=OPT_BOOST_TEMP,
        default=DEFAULT_BOOST_TEMP,
        name="Boost temperatuur",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=50,
        native_max_value=80,
        native_step=1,
        mode=NumberMode.BOX,
        icon="mdi:thermometer-high",
    ),
    DHWNumberDescription(
        key="vacation_min_temp",
        options_key=OPT_VACATION_MIN_TEMP,
        default=DEFAULT_VACATION_MIN_TEMP,
        name="Vakantie minimumtemperatuur",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=20,
        native_max_value=60,
        native_step=1,
        mode=NumberMode.BOX,
        icon="mdi:thermometer-low",
    ),
    DHWNumberDescription(
        key="legionella_temp",
        options_key=OPT_LEGIONELLA_TEMP,
        default=DEFAULT_LEGIONELLA_TEMP,
        name="Legionella temperatuur",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=60,
        native_max_value=80,
        native_step=1,
        mode=NumberMode.BOX,
        icon="mdi:bacteria",
    ),
    DHWNumberDescription(
        key="preheat_temp",
        options_key=OPT_PREHEAT_TEMP,
        default=DEFAULT_PREHEAT_TEMP,
        name="Voorverwarming temperatuur",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=25,
        native_max_value=55,
        native_step=1,
        mode=NumberMode.BOX,
        icon="mdi:thermometer-chevron-up",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DHWCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(DHWNumber(coordinator, desc) for desc in NUMBERS)


class DHWNumber(DHWEntity, NumberEntity):
    """A number entity that reads/writes a threshold stored in config entry options."""

    entity_description: DHWNumberDescription

    def __init__(self, coordinator: DHWCoordinator, description: DHWNumberDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._attr_name = description.name

    @property
    def native_value(self) -> float:
        return self.coordinator.cfg.get(
            self.entity_description.options_key, self.entity_description.default
        )

    async def async_set_native_value(self, value: float) -> None:
        new_options = {**self.coordinator.entry.options, self.entity_description.options_key: value}
        self.hass.config_entries.async_update_entry(self.coordinator.entry, options=new_options)
        await self.coordinator.async_request_refresh()
