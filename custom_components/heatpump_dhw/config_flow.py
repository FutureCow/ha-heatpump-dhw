"""Config flow for Heat Pump DHW."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TimeSelector,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    SelectOptionDict,
    BooleanSelector,
)

from .const import (
    CONF_BOILER_TEMP_SENSOR,
    CONF_DYNAMIC_PRICE_SENSOR,
    CONF_EHEATER_BOOST_TEMP_ENTITY,
    CONF_EHEATER_SWITCH,
    CONF_HEATPUMP_SWITCH,
    CONF_NOTIFY_SERVICE,
    CONF_OUTSIDE_TEMP_SENSOR,
    CONF_POWER_SENSOR,
    CONF_PRESENCE_SENSOR,
    CONF_PRICE_FORECAST_SENSOR,
    CONF_PV_PRODUCTION_SENSOR,
    CONF_PV_SURPLUS_SENSOR,
    CONF_SHOWER_SCHEDULES,
    CONF_TARGET_TEMP_ENTITY,
    CONF_WEATHER_ENTITY,
    DEFAULT_ANTI_BLOCK_DAYS,
    DEFAULT_BOOST_TEMP,
    DEFAULT_CHEAP_HOURS,
    DEFAULT_BOOST_THRESHOLD_W,
    DEFAULT_LEGIONELLA_DAY,
    DEFAULT_LEGIONELLA_HOUR,
    DEFAULT_LEGIONELLA_TEMP,
    DEFAULT_NORMAL_TEMP,
    DEFAULT_PREDICTIVE_HEATING,
    DEFAULT_PRICE_THRESHOLD_EUR,
    DEFAULT_REFERENCE_PRICE_EUR,
    DEFAULT_SOLAR_THRESHOLD_W,
    DEFAULT_TANK_VOLUME_L,
    DEFAULT_VACATION_ABSENCE_HOURS,
    DEFAULT_VACATION_MIN_TEMP,
    DOMAIN,
    OPT_ANTI_BLOCK_DAYS,
    OPT_BOOST_MODE_ENABLED,
    OPT_BOOST_TEMP,
    OPT_BOOST_THRESHOLD_W,
    OPT_LEGIONELLA_DAY,
    OPT_LEGIONELLA_HOUR,
    OPT_LEGIONELLA_MODE_ENABLED,
    OPT_LEGIONELLA_TEMP,
    OPT_NORMAL_TEMP,
    OPT_CHEAP_HOURS,
    OPT_PREDICTIVE_HEATING,
    OPT_PRICE_MODE_ENABLED,
    OPT_PRICE_THRESHOLD_EUR,
    OPT_REFERENCE_PRICE_EUR,
    OPT_SOLAR_MODE_ENABLED,
    OPT_SOLAR_THRESHOLD_W,
    OPT_TANK_VOLUME_L,
    OPT_VACATION_ABSENCE_HOURS,
    OPT_VACATION_MIN_TEMP,
)

_SENSOR = EntitySelectorConfig(domain="sensor")
_SWITCH = EntitySelectorConfig(domain=["switch", "input_boolean"])
_NUMBER = EntitySelectorConfig(domain=["number", "input_number"])
_ANY = EntitySelectorConfig(domain=["sensor", "number", "input_number", "binary_sensor", "person", "device_tracker"])


class DHWConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the multi-step config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict = {}

    async def async_step_user(self, user_input=None):
        """Step 1 — hardware sensors."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_controls()

        schema = vol.Schema(
            {
                vol.Required(CONF_BOILER_TEMP_SENSOR): EntitySelector(_SENSOR),
                vol.Optional(CONF_POWER_SENSOR): EntitySelector(_SENSOR),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_controls(self, user_input=None):
        """Step 2 — hardware controls."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_grid()

        schema = vol.Schema(
            {
                vol.Required(CONF_TARGET_TEMP_ENTITY): EntitySelector(_NUMBER),
                vol.Required(CONF_HEATPUMP_SWITCH): EntitySelector(_SWITCH),
                vol.Optional(CONF_EHEATER_SWITCH): EntitySelector(_SWITCH),
                vol.Optional(CONF_EHEATER_BOOST_TEMP_ENTITY): EntitySelector(_NUMBER),
            }
        )
        return self.async_show_form(step_id="controls", data_schema=schema)

    async def async_step_grid(self, user_input=None):
        """Step 3 — grid/solar sensors."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_optional()

        schema = vol.Schema(
            {
                vol.Optional(CONF_PV_PRODUCTION_SENSOR): EntitySelector(_SENSOR),
                vol.Optional(CONF_PV_SURPLUS_SENSOR): EntitySelector(_SENSOR),
                vol.Optional(CONF_DYNAMIC_PRICE_SENSOR): EntitySelector(_SENSOR),
                vol.Optional(CONF_PRICE_FORECAST_SENSOR): EntitySelector(_SENSOR),
            }
        )
        return self.async_show_form(step_id="grid", data_schema=schema)

    async def async_step_optional(self, user_input=None):
        """Step 4 — optional sensors."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_defaults()

        schema = vol.Schema(
            {
                vol.Optional(CONF_WEATHER_ENTITY): EntitySelector(
                    EntitySelectorConfig(domain="weather")
                ),
                vol.Optional(CONF_OUTSIDE_TEMP_SENSOR): EntitySelector(_SENSOR),
                vol.Optional(CONF_PRESENCE_SENSOR): EntitySelector(
                    EntitySelectorConfig(
                        domain=["binary_sensor", "person", "device_tracker", "input_boolean"]
                    )
                ),
                vol.Optional(CONF_NOTIFY_SERVICE): TextSelector(),
            }
        )
        return self.async_show_form(step_id="optional", data_schema=schema)

    async def async_step_defaults(self, user_input=None):
        """Step 5 — default thresholds."""
        if user_input is not None:
            self._data.update(user_input)
            title = "Heat Pump DHW"
            return self.async_create_entry(title=title, data=self._data)

        schema = _defaults_schema()
        return self.async_show_form(step_id="defaults", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> DHWOptionsFlow:
        return DHWOptionsFlow(config_entry)


_DAYS_OPTIONS = [
    SelectOptionDict(value="0", label="Maandag"),
    SelectOptionDict(value="1", label="Dinsdag"),
    SelectOptionDict(value="2", label="Woensdag"),
    SelectOptionDict(value="3", label="Donderdag"),
    SelectOptionDict(value="4", label="Vrijdag"),
    SelectOptionDict(value="5", label="Zaterdag"),
    SelectOptionDict(value="6", label="Zondag"),
]

_WEEKDAYS = ["0", "1", "2", "3", "4"]


class DHWOptionsFlow(OptionsFlow):
    """Handle options (thresholds + shower schedules) after initial setup."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Show menu: thresholds or shower schedules."""
        return self.async_show_menu(
            step_id="init",
            menu_options={
                "thresholds": "Drempelwaarden & temperaturen",
                "shower_schedules": "Douche schema's",
            },
        )

    async def async_step_thresholds(self, user_input=None):
        """Thresholds and temperature settings."""
        if user_input is not None:
            new_options = {**self._config_entry.options, **user_input}
            return self.async_create_entry(title="", data=new_options)

        schema = _defaults_schema(self._config_entry.options)
        return self.async_show_form(step_id="thresholds", data_schema=schema)

    async def async_step_shower_schedules(self, user_input=None):
        """Configure up to 3 shower schedules."""
        if user_input is not None:
            schedules = []
            for i in range(1, 4):
                if user_input.get(f"s{i}_enabled"):
                    raw_time = user_input.get(f"s{i}_time", "07:00:00")
                    # TimeSelector returns HH:MM:SS — strip seconds
                    time_str = ":".join(str(raw_time).split(":")[:2])
                    schedules.append(
                        {
                            "time": time_str,
                            "days": [int(d) for d in user_input.get(f"s{i}_days", _WEEKDAYS)],
                            "temp": float(user_input.get(f"s{i}_temp", DEFAULT_NORMAL_TEMP)),
                        }
                    )
            new_options = {**self._config_entry.options, CONF_SHOWER_SCHEDULES: schedules}
            return self.async_create_entry(title="", data=new_options)

        # Pre-fill from stored schedules
        stored = self._config_entry.options.get(CONF_SHOWER_SCHEDULES, [])
        d: dict = {}
        for i in range(1, 4):
            sched = stored[i - 1] if i - 1 < len(stored) else None
            d[f"s{i}_enabled"] = sched is not None
            d[f"s{i}_time"] = (sched["time"] + ":00") if sched else "07:00:00"
            d[f"s{i}_days"] = [str(x) for x in sched["days"]] if sched else list(_WEEKDAYS)
            d[f"s{i}_temp"] = sched["temp"] if sched else DEFAULT_NORMAL_TEMP

        def _slot(i: int) -> dict:
            return {
                vol.Optional(f"s{i}_enabled", default=d[f"s{i}_enabled"]): BooleanSelector(),
                vol.Optional(f"s{i}_time", default=d[f"s{i}_time"]): TimeSelector(),
                vol.Optional(f"s{i}_days", default=d[f"s{i}_days"]): SelectSelector(
                    SelectSelectorConfig(options=_DAYS_OPTIONS, multiple=True)
                ),
                vol.Optional(f"s{i}_temp", default=d[f"s{i}_temp"]): NumberSelector(
                    NumberSelectorConfig(min=35, max=75, step=1, unit_of_measurement="°C", mode=NumberSelectorMode.BOX)
                ),
            }

        schema = vol.Schema({**_slot(1), **_slot(2), **_slot(3)})
        return self.async_show_form(step_id="shower_schedules", data_schema=schema)


def _defaults_schema(current: dict | None = None) -> vol.Schema:
    """Build the thresholds schema, pre-filled with current values if given."""
    c = current or {}

    def _n(key, default):
        return c.get(key, default)

    return vol.Schema(
        {
            vol.Optional(OPT_SOLAR_MODE_ENABLED, default=_n(OPT_SOLAR_MODE_ENABLED, True)): BooleanSelector(),
            vol.Optional(OPT_SOLAR_THRESHOLD_W, default=_n(OPT_SOLAR_THRESHOLD_W, DEFAULT_SOLAR_THRESHOLD_W)): NumberSelector(
                NumberSelectorConfig(min=0, max=10000, step=50, unit_of_measurement="W", mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(OPT_BOOST_MODE_ENABLED, default=_n(OPT_BOOST_MODE_ENABLED, True)): BooleanSelector(),
            vol.Optional(OPT_BOOST_THRESHOLD_W, default=_n(OPT_BOOST_THRESHOLD_W, DEFAULT_BOOST_THRESHOLD_W)): NumberSelector(
                NumberSelectorConfig(min=0, max=15000, step=100, unit_of_measurement="W", mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(OPT_PRICE_MODE_ENABLED, default=_n(OPT_PRICE_MODE_ENABLED, True)): BooleanSelector(),
            vol.Optional(OPT_PRICE_THRESHOLD_EUR, default=_n(OPT_PRICE_THRESHOLD_EUR, DEFAULT_PRICE_THRESHOLD_EUR)): NumberSelector(
                NumberSelectorConfig(min=0, max=1, step=0.01, unit_of_measurement="€/kWh", mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(OPT_CHEAP_HOURS, default=_n(OPT_CHEAP_HOURS, DEFAULT_CHEAP_HOURS)): NumberSelector(
                NumberSelectorConfig(min=1, max=12, step=1, unit_of_measurement="uur", mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(OPT_NORMAL_TEMP, default=_n(OPT_NORMAL_TEMP, DEFAULT_NORMAL_TEMP)): NumberSelector(
                NumberSelectorConfig(min=35, max=80, step=1, unit_of_measurement="°C", mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(OPT_BOOST_TEMP, default=_n(OPT_BOOST_TEMP, DEFAULT_BOOST_TEMP)): NumberSelector(
                NumberSelectorConfig(min=50, max=80, step=1, unit_of_measurement="°C", mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(OPT_VACATION_MIN_TEMP, default=_n(OPT_VACATION_MIN_TEMP, DEFAULT_VACATION_MIN_TEMP)): NumberSelector(
                NumberSelectorConfig(min=20, max=60, step=1, unit_of_measurement="°C", mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(OPT_VACATION_ABSENCE_HOURS, default=_n(OPT_VACATION_ABSENCE_HOURS, DEFAULT_VACATION_ABSENCE_HOURS)): NumberSelector(
                NumberSelectorConfig(min=1, max=72, step=1, unit_of_measurement="uur", mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(OPT_LEGIONELLA_MODE_ENABLED, default=_n(OPT_LEGIONELLA_MODE_ENABLED, True)): BooleanSelector(),
            vol.Optional(OPT_LEGIONELLA_TEMP, default=_n(OPT_LEGIONELLA_TEMP, DEFAULT_LEGIONELLA_TEMP)): NumberSelector(
                NumberSelectorConfig(min=60, max=80, step=1, unit_of_measurement="°C", mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(OPT_LEGIONELLA_DAY, default=_n(OPT_LEGIONELLA_DAY, DEFAULT_LEGIONELLA_DAY)): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value="0", label="Maandag"),
                        SelectOptionDict(value="1", label="Dinsdag"),
                        SelectOptionDict(value="2", label="Woensdag"),
                        SelectOptionDict(value="3", label="Donderdag"),
                        SelectOptionDict(value="4", label="Vrijdag"),
                        SelectOptionDict(value="5", label="Zaterdag"),
                        SelectOptionDict(value="6", label="Zondag"),
                    ],
                    mode=SelectSelectorMode.LIST,
                )
            ),
            vol.Optional(OPT_LEGIONELLA_HOUR, default=_n(OPT_LEGIONELLA_HOUR, DEFAULT_LEGIONELLA_HOUR)): NumberSelector(
                NumberSelectorConfig(min=0, max=23, step=1, unit_of_measurement="u", mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(OPT_REFERENCE_PRICE_EUR, default=_n(OPT_REFERENCE_PRICE_EUR, DEFAULT_REFERENCE_PRICE_EUR)): NumberSelector(
                NumberSelectorConfig(min=0, max=2, step=0.01, unit_of_measurement="€/kWh", mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(OPT_TANK_VOLUME_L, default=_n(OPT_TANK_VOLUME_L, DEFAULT_TANK_VOLUME_L)): NumberSelector(
                NumberSelectorConfig(min=50, max=500, step=10, unit_of_measurement="L", mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(OPT_ANTI_BLOCK_DAYS, default=_n(OPT_ANTI_BLOCK_DAYS, DEFAULT_ANTI_BLOCK_DAYS)): NumberSelector(
                NumberSelectorConfig(min=1, max=14, step=1, unit_of_measurement="dagen", mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(OPT_PREDICTIVE_HEATING, default=_n(OPT_PREDICTIVE_HEATING, DEFAULT_PREDICTIVE_HEATING)): BooleanSelector(),
        }
    )
