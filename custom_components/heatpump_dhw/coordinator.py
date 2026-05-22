"""Central coordinator — reads sensors, decides mode, controls hardware."""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta, time as dt_time
from statistics import mean
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    ANTI_BLOCK_RUN_MINUTES,
    CONF_BOILER_TEMP_SENSOR,
    CONF_DYNAMIC_PRICE_SENSOR,
    CONF_ENERGY_METER_SENSOR,
    CONF_PRICE_FORECAST_SENSOR,
    CONF_EHEATER_SETPOINT_ENTITY,
    CONF_EHEATER_SWITCH,
    CONF_HEATPUMP_SWITCH,
    CONF_NOTIFY_SERVICE,
    CONF_OUTSIDE_TEMP_SENSOR,
    CONF_POWER_SENSOR,
    CONF_PRESENCE_SENSOR,
    CONF_PV_SURPLUS_SENSOR,
    CONF_SHOWER_SCHEDULES,
    CONF_TARGET_TEMP_ENTITY,
    CONF_WEATHER_ENTITY,
    DEFAULT_ANTI_BLOCK_DAYS,
    DEFAULT_BOOST_TEMP,
    DEFAULT_BOILER_SETPOINT_OFFSET,
    DEFAULT_PRICE_MODE_CONSECUTIVE,
    DEFAULT_AMBIENT_TEMP,
    DEFAULT_TANK_LOSS_RATE,
    DEFAULT_BOOST_THRESHOLD_W,
    DEFAULT_LEGIONELLA_DAY,
    DEFAULT_LEGIONELLA_HOUR,
    DEFAULT_LEGIONELLA_TEMP,
    DEFAULT_NORMAL_TEMP,
    DEFAULT_PREDICTIVE_HEATING,
    DEFAULT_SOLAR_THRESHOLD_W,
    DEFAULT_TANK_VOLUME_L,
    DEFAULT_VACATION_ABSENCE_HOURS,
    DEFAULT_VACATION_MIN_TEMP,
    OPT_BOILER_SETPOINT_OFFSET,
    OPT_PREHEAT_TEMP,
    DEFAULT_PREHEAT_TEMP,
    OPT_PRICE_MODE_CONSECUTIVE,
    OPT_TANK_LOSS_RATE,
    DOMAIN,
    HEAT_UP_SAMPLE_SIZE,
    MIN_CYCLE_MINUTES,
    MODE_ANTI_BLOCK,
    MODE_BOOST,
    MODE_IDLE,
    MODE_LEGIONELLA,
    MODE_MANUAL,
    MODE_PRICE,
    MODE_SCHEDULE,
    MODE_SOLAR,
    MODE_VACATION,
    OPT_ANTI_BLOCK_DAYS,
    OPT_BOOST_MODE_ENABLED,
    OPT_BOOST_TEMP,
    OPT_BOOST_THRESHOLD_W,
    OPT_LEGIONELLA_DAY,
    OPT_LEGIONELLA_HOUR,
    OPT_LEGIONELLA_MODE_ENABLED,
    OPT_LEGIONELLA_TEMP,
    OPT_NORMAL_TEMP,
    OPT_PREDICTIVE_HEATING,
    OPT_PRICE_MODE_ENABLED,
    OPT_SOLAR_MODE_ENABLED,
    OPT_SOLAR_THRESHOLD_W,
    OPT_TANK_VOLUME_L,
    OPT_VACATION_ABSENCE_HOURS,
    OPT_VACATION_MIN_TEMP,
    STORAGE_KEY,
    STORAGE_VERSION,
    SUNNY_CONDITIONS,
    TEMP_HYSTERESIS,
    UPDATE_INTERVAL,
    WATER_SPECIFIC_HEAT_KJ,
)

_LOGGER = logging.getLogger(__name__)


class DHWCoordinator(DataUpdateCoordinator):
    """Polls sensors, determines heating mode, and controls the boiler."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self.entry = entry
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)

        # Runtime state
        self._active_mode: str = MODE_IDLE
        self._heating: bool = False
        self._last_switch_time: datetime | None = None
        self._anti_block_start: datetime | None = None

        # Session tracking
        self._session_start: datetime | None = None
        self._session_start_temp: float | None = None
        self._session_start_meter: float | None = None
        self._last_session: dict = {}
        self._session_notified: bool = False
        self._last_set_temp: float | None = None

        # Energy meter tracking
        self._energy_meter_prev: float | None = None
        self._month_start_meter: float | None = None
        self._year_start_meter: float | None = None

        # Persisted data (loaded from storage)
        self._heat_up_samples: list[float] = []
        self._cop_samples: list[float] = []
        self._loss_samples: list[float] = []  # °C/hour tank heat loss measurements
        self._heat_rate_samples: list[float] = []  # °C/hour heating rate measurements
        self._last_legionella_run: datetime | None = None
        self._last_pump_run: datetime | None = None
        self._monthly_kwh: float = 0.0
        self._monthly_cost: float = 0.0
        self._monthly_month: int = datetime.now().month
        self._yearly_kwh: float = 0.0
        self._yearly_cost: float = 0.0
        self._yearly_year: int = datetime.now().year

        # For auto-learning heat loss rate
        self._last_idle_temp: float | None = None
        self._last_idle_time: datetime | None = None

        # Mode switches — toggled by switch entities
        self.solar_mode_enabled: bool = True
        self.price_mode_enabled: bool = True
        self.boost_mode_enabled: bool = True
        self.legionella_mode_enabled: bool = True
        self.vacation_mode_enabled: bool = False

        self._manual_heat: bool = False
        self._manual_heat_start_temp: float | None = None  # boilertemp bij activatie
        self._manual_heat_since: datetime | None = None   # tijdstip van activatie

        # Absence tracking for delayed vacation mode
        self._absence_start: datetime | None = None
        self._vacation_manual: bool = False   # handmatig "op vakantie" gezet
        self._vacation_active: bool = False

        # Track sent shower warnings to avoid spam
        self._shower_warning_sent: set[str] = set()

        self._next_heating: datetime | None = None
        self._planned_slots: list[str] = []

    # ------------------------------------------------------------------
    # Public properties for switch entities
    # ------------------------------------------------------------------

    @property
    def manual_heat_enabled(self) -> bool:
        return self._manual_heat

    @manual_heat_enabled.setter
    def manual_heat_enabled(self, value: bool) -> None:
        self._manual_heat = value
        if value:
            self._manual_heat_since = dt_util.now()
        else:
            self._manual_heat_start_temp = None
            self._manual_heat_since = None

    # ------------------------------------------------------------------
    # Setup / teardown
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        stored = await self._store.async_load() or {}
        self._heat_up_samples = stored.get("heat_up_samples", [])
        self._cop_samples = stored.get("cop_samples", [])
        # loss_samples stores normalised k values (°C/h per °C ΔT) since storage_version 2.
        # Discard once on migration from the old raw °C/h format.
        if stored.get("storage_version", 1) >= 2:
            self._loss_samples = stored.get("loss_samples", [])
        else:
            self._loss_samples = []
        self._heat_rate_samples = stored.get("heat_rate_samples", [])
        raw_ll = stored.get("last_legionella_run")
        self._last_legionella_run = datetime.fromisoformat(raw_ll) if raw_ll else None
        raw_lp = stored.get("last_pump_run")
        self._last_pump_run = datetime.fromisoformat(raw_lp) if raw_lp else None
        raw_abs = stored.get("absence_start")
        self._absence_start = datetime.fromisoformat(raw_abs) if raw_abs else None
        self._vacation_manual = stored.get("vacation_manual", False)
        self._vacation_active = self._vacation_manual
        self._monthly_kwh = stored.get("monthly_kwh", 0.0)
        self._monthly_cost = stored.get("monthly_cost", 0.0)
        self._monthly_month = stored.get("monthly_month", datetime.now().month)
        self._yearly_kwh = stored.get("yearly_kwh", 0.0)
        self._yearly_cost = stored.get("yearly_cost", 0.0)
        self._yearly_year = stored.get("yearly_year", datetime.now().year)
        self._month_start_meter = stored.get("month_start_meter")
        self._year_start_meter = stored.get("year_start_meter")
        self._last_session = stored.get("last_session", {})

        opts = self.entry.options
        self.solar_mode_enabled = stored.get("solar_mode_enabled", opts.get(OPT_SOLAR_MODE_ENABLED, True))
        self.price_mode_enabled = stored.get("price_mode_enabled", opts.get(OPT_PRICE_MODE_ENABLED, True))
        self.boost_mode_enabled = stored.get("boost_mode_enabled", opts.get(OPT_BOOST_MODE_ENABLED, True))
        self.legionella_mode_enabled = stored.get("legionella_mode_enabled", opts.get(OPT_LEGIONELLA_MODE_ENABLED, True))
        self.vacation_mode_enabled = stored.get("vacation_mode_enabled", False)

    async def async_shutdown(self) -> None:
        await self._save_state()

    async def _save_state(self) -> None:
        await self._store.async_save(
            {
                "storage_version": 2,
                "heat_up_samples": self._heat_up_samples[-HEAT_UP_SAMPLE_SIZE:],
                "cop_samples": self._cop_samples[-HEAT_UP_SAMPLE_SIZE:],
                "loss_samples": self._loss_samples[-HEAT_UP_SAMPLE_SIZE:],
                "heat_rate_samples": self._heat_rate_samples[-HEAT_UP_SAMPLE_SIZE:],
                "last_legionella_run": self._last_legionella_run.isoformat() if self._last_legionella_run else None,
                "last_pump_run": self._last_pump_run.isoformat() if self._last_pump_run else None,
                "absence_start": self._absence_start.isoformat() if self._absence_start else None,
                "vacation_manual": self._vacation_manual,
                "solar_mode_enabled": self.solar_mode_enabled,
                "price_mode_enabled": self.price_mode_enabled,
                "boost_mode_enabled": self.boost_mode_enabled,
                "legionella_mode_enabled": self.legionella_mode_enabled,
                "vacation_mode_enabled": self.vacation_mode_enabled,
                "monthly_kwh": self._monthly_kwh,
                "monthly_cost": self._monthly_cost,
                "monthly_month": self._monthly_month,
                "yearly_kwh": self._yearly_kwh,
                "yearly_cost": self._yearly_cost,
                "yearly_year": self._yearly_year,
                "month_start_meter": self._month_start_meter,
                "year_start_meter": self._year_start_meter,
                "last_session": self._last_session,
            }
        )

    # ------------------------------------------------------------------
    # Options / config helpers
    # ------------------------------------------------------------------

    def _opt(self, key: str, default):
        if key in self.entry.options:
            return self.entry.options[key]
        return self.entry.data.get(key, default)

    def _effective_hysteresis(self) -> float:
        """Dead band for heating decisions: max of built-in hysteresis and boiler setpoint offset.

        Some boilers won't activate unless temp is at least N °C below setpoint.
        Setting boiler_setpoint_offset to that value prevents futile on-commands.
        """
        offset = float(self._opt(OPT_BOILER_SETPOINT_OFFSET, DEFAULT_BOILER_SETPOINT_OFFSET))
        return max(TEMP_HYSTERESIS, offset)

    @property
    def cfg(self):
        return {**self.entry.data, **self.entry.options}

    # ------------------------------------------------------------------
    # Sensor reading helpers
    # ------------------------------------------------------------------

    def _state_float(self, entity_id: str | None) -> float | None:
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable", ""):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def _state_watts(self, entity_id: str | None) -> float | None:
        """Read a power sensor and convert kW → W automatically."""
        value = self._state_float(entity_id)
        if value is None:
            return None
        state = self.hass.states.get(entity_id)
        uom = (state.attributes.get("unit_of_measurement") or "").lower()
        if uom in ("kw", "kilowatt", "kilowatts"):
            value *= 1000
        return value

    def _state_bool(self, entity_id: str | None) -> bool | None:
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        return state.state in ("on", "home", "true", "True")

    def _weather_forecast_tomorrow_sunny(self) -> bool:
        """Return True if tomorrow morning's forecast looks sunny."""
        entity_id = self.cfg.get(CONF_WEATHER_ENTITY)
        if not entity_id:
            return False
        state = self.hass.states.get(entity_id)
        if not state:
            return False
        forecast = state.attributes.get("forecast", [])
        tomorrow = (dt_util.now() + timedelta(days=1)).date()
        for entry in forecast:
            try:
                entry_date = datetime.fromisoformat(entry.get("datetime", "")).date()
            except (ValueError, TypeError):
                continue
            if entry_date == tomorrow:
                return entry.get("condition", "") in SUNNY_CONDITIONS
        return False

    # ------------------------------------------------------------------
    # Core update loop
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        now = dt_util.now()

        boiler_temp, power_w, meter_kwh, surplus_w, price_eur, outside_temp, present = (
            self._read_sensors()
        )
        self._init_meter_baselines(meter_kwh)
        self._sync_switch_state(now)

        desired_mode, desired_temp = self._decide_mode(
            now, boiler_temp, surplus_w, price_eur, present
        )

        await self._track_session(boiler_temp, power_w, price_eur, outside_temp, meter_kwh, now, desired_temp)
        await self._apply_control(desired_mode, desired_temp, boiler_temp, power_w, meter_kwh, now)

        self._energy_meter_prev = meter_kwh
        self._learn_heat_loss(boiler_temp, now, outside_temp)
        await self._check_shower_readiness(now, boiler_temp)

        self._next_heating = self._calc_next_heating(now)
        self._planned_slots = self._calc_planned_slots(now)

        self._handle_period_resets(meter_kwh, now)
        await self._save_state()

        return self._build_data_dict(
            boiler_temp, power_w, surplus_w, price_eur, outside_temp,
            desired_mode, desired_temp, meter_kwh,
        )

    def _read_sensors(self) -> tuple:
        """Read all HA sensor states and return them as a tuple."""
        return (
            self._state_float(self.cfg.get(CONF_BOILER_TEMP_SENSOR)),
            self._state_watts(self.cfg.get(CONF_POWER_SENSOR)),
            self._state_float(self.cfg.get(CONF_ENERGY_METER_SENSOR)),
            self._state_watts(self.cfg.get(CONF_PV_SURPLUS_SENSOR)),
            self._state_float(self.cfg.get(CONF_DYNAMIC_PRICE_SENSOR)),
            self._state_float(self.cfg.get(CONF_OUTSIDE_TEMP_SENSOR)),
            self._state_bool(self.cfg.get(CONF_PRESENCE_SENSOR)),
        )

    def _init_meter_baselines(self, meter_kwh: float | None) -> None:
        """Set month/year meter baselines on first reading.

        Reconstructs from stored accumulated kWh when the start value is missing
        (first run or store corruption) to avoid resetting the running total.
        """
        if meter_kwh is None:
            return
        if self._month_start_meter is None:
            self._month_start_meter = (
                meter_kwh - self._monthly_kwh if self._monthly_kwh > 0 else meter_kwh
            )
        if self._year_start_meter is None:
            self._year_start_meter = (
                meter_kwh - self._yearly_kwh if self._yearly_kwh > 0 else meter_kwh
            )

    def _sync_switch_state(self, now: datetime) -> None:
        """Sync self._heating with the actual hardware switch state.

        Detects external changes (defrost, manual override, power loss) and
        sets the anti-short-cycle timer so the coordinator doesn't immediately
        counter the external action.
        """
        hp_switch = self.cfg.get(CONF_HEATPUMP_SWITCH)
        if not hp_switch:
            return
        actual_on = self._state_bool(hp_switch)
        if actual_on is not None and actual_on != self._heating:
            _LOGGER.info(
                "DHW: warmtepomp schakelaar extern gewijzigd naar %s — sync state",
                "aan" if actual_on else "uit",
            )
            self._heating = actual_on
            self._last_switch_time = now

    def _handle_period_resets(self, meter_kwh: float | None, now: datetime) -> None:
        """Reset monthly/yearly accumulators on rollover and sync kWh with the live meter."""
        if now.month != self._monthly_month:
            _LOGGER.debug(
                "DHW: maandelijkse reset (opgeslagen maand=%s, huidige maand=%s, kosten voor reset=%.3f)",
                self._monthly_month, now.month, self._monthly_cost,
            )
            self._monthly_kwh = 0.0
            self._monthly_cost = 0.0
            self._monthly_month = now.month
            self._month_start_meter = meter_kwh
        if now.year != self._yearly_year:
            _LOGGER.debug(
                "DHW: jaarlijkse reset (opgeslagen jaar=%s, huidig jaar=%s, kosten voor reset=%.3f)",
                self._yearly_year, now.year, self._yearly_cost,
            )
            self._yearly_kwh = 0.0
            self._yearly_cost = 0.0
            self._yearly_year = now.year
            self._year_start_meter = meter_kwh

        if meter_kwh is not None:
            if self._month_start_meter is not None:
                self._monthly_kwh = max(0.0, meter_kwh - self._month_start_meter)
            if self._year_start_meter is not None:
                self._yearly_kwh = max(0.0, meter_kwh - self._year_start_meter)

    def _build_data_dict(
        self,
        boiler_temp: float | None,
        power_w: float | None,
        surplus_w: float | None,
        price_eur: float | None,
        outside_temp: float | None,
        desired_mode: str,
        desired_temp: float,
        meter_kwh: float | None,
    ) -> dict[str, Any]:
        """Build the data dictionary returned to HA sensor/switch entities."""
        return {
            "boiler_temp": boiler_temp,
            "power_w": power_w,
            "surplus_w": surplus_w,
            "price_eur": price_eur,
            "outside_temp": outside_temp,
            "active_mode": self._active_mode,
            "heating": self._heating,
            "session_kwh": (
                round(meter_kwh - self._session_start_meter, 3)
                if meter_kwh is not None and self._session_start_meter is not None and self._heating
                else self._last_session.get("kwh", 0.0)
            ),
            "session_cost": self._last_session.get("cost", 0.0),
            "session_cop": self._last_session.get("cop"),
            "avg_cop": mean(self._cop_samples) if self._cop_samples else None,
            "next_heating": self._next_heating.isoformat() if self._next_heating else None,
            "planned_heating_slots": self._planned_slots,
            "heat_up_duration_min": round(mean(self._heat_up_samples)) if self._heat_up_samples else None,
            "monthly_kwh": (
                round(meter_kwh - self._month_start_meter, 3)
                if meter_kwh is not None and self._month_start_meter is not None
                else round(self._monthly_kwh, 3)
            ),
            "monthly_cost": round(self._monthly_cost, 2),
            "yearly_kwh": (
                round(meter_kwh - self._year_start_meter, 3)
                if meter_kwh is not None and self._year_start_meter is not None
                else round(self._yearly_kwh, 3)
            ),
            "yearly_cost": round(self._yearly_cost, 2),
            "learned_loss_rate": round(self._loss_rate_at(
                float(self._opt(OPT_NORMAL_TEMP, DEFAULT_NORMAL_TEMP)), outside_temp
            ), 2) if self._loss_samples else None,
            "learned_heat_rate": round(mean(self._heat_rate_samples), 1) if self._heat_rate_samples else None,
            "status_text": self._build_status_text(
                boiler_temp, surplus_w, price_eur, outside_temp, desired_temp
            ),
        }

    def _learn_heat_loss(self, boiler_temp: float | None, now: datetime, outside_temp: float | None) -> None:
        """Measure normalised heat loss coefficient k (°C/h per °C ΔT above ambient).

        Storing k instead of a raw °C/h rate corrects for the temperature dependency
        of heat loss (Newton's law of cooling): loss ∝ (T_water − T_ambient).
        """
        if self._heating:
            # Pump started: invalidate the idle baseline so the next measurement
            # starts fresh after the heating session ends.
            self._last_idle_temp = None
            self._last_idle_time = None
            return
        if boiler_temp is None:
            # Sensor temporarily unavailable — preserve the idle baseline so a
            # brief network blip doesn't discard hours of measurement data.
            return

        if self._last_idle_temp is None:
            self._last_idle_temp = boiler_temp
            self._last_idle_time = now
            return

        elapsed_hours = (now - self._last_idle_time).total_seconds() / 3600
        if elapsed_hours >= 0.5:
            drop = self._last_idle_temp - boiler_temp
            if drop > 0:
                rate = drop / elapsed_hours  # °C/h at current temperatures
                avg_temp = (self._last_idle_temp + boiler_temp) / 2
                ambient = outside_temp if outside_temp is not None else DEFAULT_AMBIENT_TEMP
                delta_t = avg_temp - ambient
                if delta_t > 5.0:  # only normalise when ΔT is meaningful
                    k = rate / delta_t  # °C/h per °C ΔT
                    if 0.001 <= k <= 0.15:  # sanity: ~0.04 typical well-insulated tank
                        self._loss_samples.append(k)
                        if len(self._loss_samples) > HEAT_UP_SAMPLE_SIZE:
                            self._loss_samples.pop(0)
            self._last_idle_temp = boiler_temp
            self._last_idle_time = now

    def _loss_rate_at(self, temp: float, outside_temp: float | None) -> float:
        """Return heat loss rate (°C/h) at given water temperature."""
        ambient = outside_temp if outside_temp is not None else DEFAULT_AMBIENT_TEMP
        if self._loss_samples:
            k = mean(self._loss_samples)
        else:
            # Default k derived from configured flat rate at 55°C reference
            default_rate = float(self._opt(OPT_TANK_LOSS_RATE, DEFAULT_TANK_LOSS_RATE))
            k = default_rate / max(1.0, 55.0 - DEFAULT_AMBIENT_TEMP)
        return k * max(0.0, temp - ambient)

    # ------------------------------------------------------------------
    # Price forecast helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_local_hour(dt: datetime, tz) -> datetime:
        """Convert a datetime to local timezone and truncate to the hour."""
        return dt.astimezone(tz).replace(minute=0, second=0, microsecond=0)

    @staticmethod
    def _to_local_slot(dt: datetime, tz, slot_minutes: int) -> datetime:
        """Convert a datetime to local timezone and truncate to the nearest slot boundary."""
        local = dt.astimezone(tz)
        return local.replace(
            minute=(local.minute // slot_minutes) * slot_minutes,
            second=0, microsecond=0,
        )

    @staticmethod
    def _detect_slot_minutes(prices: list[tuple[datetime, float]]) -> int:
        """Detect price resolution (15, 30, or 60 min) from consecutive timestamps."""
        if len(prices) < 2:
            return 60
        intervals = []
        for i in range(min(6, len(prices) - 1)):
            delta = int(round((prices[i + 1][0] - prices[i][0]).total_seconds() / 60))
            if delta > 0:
                intervals.append(delta)
        if not intervals:
            return 60
        median = sorted(intervals)[len(intervals) // 2]
        return median if median in (15, 30, 60) else 60

    @staticmethod
    def _parse_iso(s: str) -> datetime:
        """Parse ISO-8601 string; handles Z suffix and naive datetimes."""
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))

    def _get_forecast_prices(self, now: datetime, hours: int = 24) -> list[tuple[datetime, float]]:
        """Return (hour_dt, price_eur) pairs from the forecast sensor.

        Supported attribute formats:
        - Zonneplan app:      forecast [{datetime, electricity_price (millionths €)}]
        - Zonneplan template: prices_today/prices_tomorrow [{time, price}]
        - Nordpool/ENTSOE:    raw_today/raw_tomorrow [{start, value}]
        - Tibber:             prices / price_info [{startsAt, total}]
        - Generic list:       any list attr with {start|time|datetime|startsAt|hour|timestamp,
                                                   price|value|total|amount|price_ct} entries
        """
        entity_id = self.cfg.get(CONF_PRICE_FORECAST_SENSOR) or self.cfg.get(CONF_DYNAMIC_PRICE_SENSOR)
        if not entity_id:
            return []
        state = self.hass.states.get(entity_id)
        if not state:
            return []

        attrs = state.attributes
        raw_entries: list[dict] = []
        fmt_name = "unknown"

        def _load_list(val):
            if isinstance(val, str):
                try:
                    val = json.loads(val)
                except (json.JSONDecodeError, ValueError):
                    return []
            return val if isinstance(val, list) else []

        # ── Zonneplan app: attribute "forecast" [{datetime, electricity_price}] ──
        zp_forecast = _load_list(attrs.get("forecast", []))
        if zp_forecast and isinstance(zp_forecast[0], dict) and "electricity_price" in zp_forecast[0]:
            for entry in zp_forecast:
                if "datetime" in entry and "electricity_price" in entry:
                    raw_entries.append({
                        "time": entry["datetime"],
                        "price": float(entry["electricity_price"]) / 1_000_000,
                    })
            fmt_name = "Zonneplan-app"

        # ── Zonneplan template: prices_today/prices_tomorrow [{time, price}] ──
        if not raw_entries:
            for key in ("prices_today", "prices_tomorrow"):
                raw_entries.extend(_load_list(attrs.get(key, [])))
            if raw_entries:
                fmt_name = "Zonneplan-template"

        # ── Nordpool / ENTSOE: raw_today/raw_tomorrow [{start, value}] ──
        if not raw_entries:
            for key in ("raw_today", "raw_tomorrow"):
                for entry in _load_list(attrs.get(key, [])):
                    if "start" in entry and "value" in entry:
                        raw_entries.append({"time": entry["start"], "price": entry["value"]})
            if raw_entries:
                fmt_name = "Nordpool"

        # ── Tibber: prices / price_info [{startsAt, total}] ──
        if not raw_entries:
            for key in ("prices", "price_info", "today", "tomorrow"):
                for entry in _load_list(attrs.get(key, [])):
                    if isinstance(entry, dict) and "startsAt" in entry and "total" in entry:
                        raw_entries.append({"time": entry["startsAt"], "price": entry["total"]})
            if raw_entries:
                fmt_name = "Tibber"

        # ── Generic fallback: scan all list attributes for known time/price field names ──
        if not raw_entries:
            TIME_KEYS = ("start", "time", "datetime", "startsAt", "hour", "timestamp", "start_time")
            PRICE_KEYS = ("price", "value", "total", "amount", "price_ct", "electricity_price")
            for attr_key, attr_val in attrs.items():
                entries = _load_list(attr_val)
                if not entries or not isinstance(entries[0], dict):
                    continue
                first = entries[0]
                t_key = next((k for k in TIME_KEYS if k in first), None)
                p_key = next((k for k in PRICE_KEYS if k in first), None)
                if t_key and p_key:
                    multiplier = 1.0
                    if p_key == "electricity_price":
                        multiplier = 1 / 1_000_000
                    elif p_key == "price_ct":
                        multiplier = 1 / 100
                    for entry in entries:
                        if t_key in entry and p_key in entry:
                            raw_entries.append({"time": entry[t_key], "price": float(entry[p_key]) * multiplier})
                    fmt_name = f"generic({attr_key}:{t_key}/{p_key})"
                    break

        if not raw_entries:
            _LOGGER.debug("%s: no forecast entries found in sensor %s", DOMAIN, entity_id)
            return []

        _LOGGER.debug("%s: forecast format=%s, raw entries=%d", DOMAIN, fmt_name, len(raw_entries))

        now_hour = now.replace(minute=0, second=0, microsecond=0)
        cutoff = now + timedelta(hours=hours)
        result: list[tuple[datetime, float]] = []
        for entry in raw_entries:
            try:
                t = self._parse_iso(entry.get("time", ""))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=now.tzinfo)
                p = float(entry.get("price", 0))
                if now_hour <= t < cutoff:
                    result.append((t, p))
            except (ValueError, TypeError):
                continue

        _LOGGER.debug("%s: %d entries within window of %dh", DOMAIN, len(result), hours)
        return sorted(result, key=lambda x: x[0])

    def _needed_cheap_hours(self, boiler_temp: float | None, target_temp: float) -> int:
        """Calculate how many cheap hours are needed based on learned heating rate."""
        if boiler_temp is None or boiler_temp >= target_temp - self._effective_hysteresis():
            return 0
        delta = max(0.0, target_temp - boiler_temp)
        if self._heat_rate_samples:
            rate = mean(self._heat_rate_samples)  # °C/hour
            return max(1, math.ceil(delta / rate))
        # No rate data yet: estimate at a conservative 5 °C/h (typical heat-pump DHW rate).
        return max(1, math.ceil(delta / 5.0))

    def _upcoming_showers(
        self, now: datetime, schedules: list[dict], normal_temp: float, hours: int = 48
    ) -> list[tuple[datetime, float]]:
        """Return upcoming shower (shower_dt, required_temp) pairs sorted by deadline."""
        upcoming: list[tuple[datetime, float]] = []
        for sched in schedules:
            days = sched.get("days", list(range(7)))
            shower_time = dt_time.fromisoformat(sched.get("time", "07:30"))
            required_temp = float(sched.get("temp", normal_temp))
            for day_offset in range(int(hours / 24) + 2):
                candidate = now + timedelta(days=day_offset)
                if candidate.weekday() not in days:
                    continue
                shower_dt = datetime.combine(candidate.date(), shower_time, tzinfo=now.tzinfo)
                if shower_dt <= now:
                    continue
                if (shower_dt - now).total_seconds() / 3600 > hours:
                    continue
                upcoming.append((shower_dt, required_temp))
        upcoming.sort(key=lambda x: x[0])
        return upcoming

    def _in_cheap_slot_for_deadline(
        self,
        now: datetime,
        shower_dt: datetime,
        target_temp: float,
        heat_up_min: float,
        boiler_temp: float | None,
    ) -> bool | None:
        """Return True if now is a cheap heating slot for shower_dt, None if no forecast."""
        n_needed = self._needed_cheap_hours(boiler_temp, target_temp)
        if n_needed == 0:
            return False
        window_end = shower_dt - timedelta(minutes=heat_up_min)
        if window_end <= now:
            return False
        hours_to_end = math.ceil((window_end - now).total_seconds() / 3600) + 1
        prices = self._get_forecast_prices(now, hours=hours_to_end)
        if not prices:
            return None
        slot_minutes = self._detect_slot_minutes(prices)
        current_slot = now.replace(
            minute=(now.minute // slot_minutes) * slot_minutes,
            second=0, microsecond=0,
        )
        feasible = [
            (t, p) for t, p in prices
            if self._to_local_slot(t, now.tzinfo, slot_minutes) >= current_slot
            and t + timedelta(minutes=heat_up_min) <= shower_dt
        ]
        if not feasible:
            return None
        n_slots = n_needed * (60 // slot_minutes)
        consecutive = self._opt(OPT_PRICE_MODE_CONSECUTIVE, DEFAULT_PRICE_MODE_CONSECUTIVE)
        if consecutive and n_slots > 1:
            slot_seconds = slot_minutes * 60
            best_start: datetime | None = None
            best_cost = float("inf")
            for i in range(len(feasible) - n_slots + 1):
                block = feasible[i : i + n_slots]
                if any(
                    (block[j + 1][0] - block[j][0]).total_seconds() != slot_seconds
                    for j in range(n_slots - 1)
                ):
                    continue
                total = sum(p for _, p in block)
                if total < best_cost:
                    best_cost = total
                    best_start = block[0][0]
            if best_start is None:
                return False
            block_end = best_start + timedelta(minutes=slot_minutes * n_slots)
            ls = self._to_local_slot(best_start, now.tzinfo, slot_minutes)
            le = self._to_local_slot(block_end, now.tzinfo, slot_minutes)
            return ls <= current_slot < le
        else:
            cheapest_slots = {
                self._to_local_slot(t, now.tzinfo, slot_minutes)
                for t, _ in sorted(feasible, key=lambda x: x[1])[:n_slots]
            }
            return current_slot in cheapest_slots

    def _planned_slots_for_deadline(
        self,
        now: datetime,
        shower_dt: datetime,
        target_temp: float,
        heat_up_min: float,
        boiler_temp: float | None,
    ) -> list[datetime]:
        """Return sorted list of planned heating slot datetimes for a shower deadline."""
        n_needed = self._needed_cheap_hours(boiler_temp, target_temp)
        if n_needed == 0:
            return []
        window_end = shower_dt - timedelta(minutes=heat_up_min)
        if window_end <= now:
            return []
        hours_to_end = math.ceil((window_end - now).total_seconds() / 3600) + 1
        prices = self._get_forecast_prices(now, hours=hours_to_end)
        if not prices:
            return []
        slot_minutes = self._detect_slot_minutes(prices)
        current_slot = now.replace(
            minute=(now.minute // slot_minutes) * slot_minutes,
            second=0, microsecond=0,
        )
        feasible = [
            (t, p) for t, p in prices
            if self._to_local_slot(t, now.tzinfo, slot_minutes) >= current_slot
            and t + timedelta(minutes=heat_up_min) <= shower_dt
        ]
        if not feasible:
            return []
        n_slots = n_needed * (60 // slot_minutes)
        consecutive = self._opt(OPT_PRICE_MODE_CONSECUTIVE, DEFAULT_PRICE_MODE_CONSECUTIVE)
        if consecutive and n_slots > 1:
            slot_seconds = slot_minutes * 60
            best_start: datetime | None = None
            best_cost = float("inf")
            for i in range(len(feasible) - n_slots + 1):
                block = feasible[i : i + n_slots]
                if any(
                    (block[j + 1][0] - block[j][0]).total_seconds() != slot_seconds
                    for j in range(n_slots - 1)
                ):
                    continue
                total = sum(p for _, p in block)
                if total < best_cost:
                    best_cost = total
                    best_start = block[0][0]
            if best_start is None:
                return []
            return [
                self._to_local_slot(
                    best_start + timedelta(minutes=slot_minutes * i), now.tzinfo, slot_minutes
                )
                for i in range(n_slots)
            ]
        else:
            cheapest = sorted(feasible, key=lambda x: x[1])[:n_slots]
            return sorted(
                self._to_local_slot(t, now.tzinfo, slot_minutes) for t, _ in cheapest
            )

    def _decide_price_schedule(
        self,
        now: datetime,
        boiler_temp: float | None,
        normal_temp: float,
        skip_predictive: bool = False,
    ) -> tuple[str, float] | None:
        """Deadline-aware price + schedule mode (merged).

        For each upcoming shower finds cheapest hours in [now .. deadline - heat_up_min].
        Emergency heating fires within 2× heat_up_min regardless of price or predictive flag.
        Returns (MODE_SCHEDULE, target_temp) or None.
        """
        schedules = self.entry.options.get(CONF_SHOWER_SCHEDULES, [])
        if not schedules:
            return None

        heat_up_min = mean(self._heat_up_samples) if self._heat_up_samples else 60.0
        preheat_temp = self._opt(OPT_PREHEAT_TEMP, DEFAULT_PREHEAT_TEMP)
        upcoming = self._upcoming_showers(now, schedules, normal_temp)

        for shower_dt, required_temp in upcoming:
            hours_until = (shower_dt - now).total_seconds() / 3600
            use_preheat = preheat_temp < required_temp and hours_until > 12.0
            target_temp = preheat_temp if use_preheat else required_temp

            if boiler_temp is not None and boiler_temp >= target_temp - self._effective_hysteresis():
                continue

            # Emergency: heat regardless of price/predictive within 2× heat_up_min
            if hours_until * 60 <= 2 * heat_up_min:
                return MODE_SCHEDULE, required_temp

            # Keep active session running — don't interrupt for new prices
            if self._heating and self._active_mode in (MODE_PRICE, MODE_SCHEDULE):
                return MODE_SCHEDULE, target_temp

            if skip_predictive:
                continue

            result = self._in_cheap_slot_for_deadline(
                now, shower_dt, target_temp, heat_up_min, boiler_temp
            )
            if result is True:
                return MODE_SCHEDULE, target_temp
            if result is None:
                # No forecast — fixed fallback: start within heat_up_min + 10 min of shower
                if (shower_dt - now).total_seconds() / 60 <= heat_up_min + 10:
                    return MODE_SCHEDULE, required_temp

        return None

    # ------------------------------------------------------------------
    # Mode decision — priority order
    # ------------------------------------------------------------------

    def _decide_mode(
        self,
        now: datetime,
        boiler_temp: float | None,
        surplus_w: float | None,
        price_eur: float | None,
        present: bool | None,
    ) -> tuple[str, float]:
        normal_temp = self._opt(OPT_NORMAL_TEMP, DEFAULT_NORMAL_TEMP)

        # 0. Handmatig aan
        if self._manual_heat:
            # Leg starttemperatuur vast op eerste tick na activatie
            if boiler_temp is not None and self._manual_heat_start_temp is None:
                self._manual_heat_start_temp = boiler_temp
            start_was_below = (
                self._manual_heat_start_temp is not None
                and self._manual_heat_start_temp < normal_temp - TEMP_HYSTERESIS
            )
            reached_target = (
                boiler_temp is not None
                and boiler_temp >= normal_temp - TEMP_HYSTERESIS
            )
            # Safety timeout: als de boiler na 4 uur nog steeds onder de doeltemperatuur
            # staat, is er waarschijnlijk iets mis (storing, stroomuitval). Reset dan
            # automatisch zodat Legionella en andere veiligheidsmodi niet geblokkeerd blijven.
            timed_out = (
                self._manual_heat_since is not None
                and (now - self._manual_heat_since).total_seconds() > 4 * 3600
                and not reached_target
            )
            if timed_out:
                _LOGGER.warning(
                    "DHW: handmatige modus timeout na 4u, boiler %.1f°C < %.1f°C — auto-reset",
                    boiler_temp if boiler_temp is not None else -99,
                    normal_temp - TEMP_HYSTERESIS,
                )
            if (start_was_below and reached_target) or timed_out:
                self._manual_heat = False
                self._manual_heat_start_temp = None
                self._manual_heat_since = None
            else:
                return MODE_MANUAL, normal_temp

        # 1. Anti-block: force short run if pump idle too long
        anti_block_days = self._opt(OPT_ANTI_BLOCK_DAYS, DEFAULT_ANTI_BLOCK_DAYS)
        idle_days = (
            (now - self._last_pump_run).total_seconds() / 86400
            if self._last_pump_run else 999
        )
        if idle_days >= anti_block_days:
            if self._anti_block_start is None:
                self._anti_block_start = now
            elapsed_min = (now - self._anti_block_start).total_seconds() / 60
            if elapsed_min < ANTI_BLOCK_RUN_MINUTES:
                return MODE_ANTI_BLOCK, normal_temp
            # Run completed — reset
            self._anti_block_start = None
            self._last_pump_run = now

        # 2. Legionella — weekly safety run
        if self.legionella_mode_enabled and self._is_legionella_time(now):
            leg_temp = self._opt(OPT_LEGIONELLA_TEMP, DEFAULT_LEGIONELLA_TEMP)
            if boiler_temp is None or boiler_temp < leg_temp - self._effective_hysteresis():
                return MODE_LEGIONELLA, leg_temp

        # 3. Vacation status — detect before boost/solar/price so those modes respect it
        if self.vacation_mode_enabled and not self._vacation_manual:
            absence_hours = self._opt(OPT_VACATION_ABSENCE_HOURS, DEFAULT_VACATION_ABSENCE_HOURS)
            if present is True:
                self._absence_start = None
                self._vacation_active = False
            elif present is False:
                if self._absence_start is None:
                    self._absence_start = now
            absent_long_enough = (
                self._absence_start is not None
                and (now - self._absence_start).total_seconds() / 3600 >= absence_hours
            )
            if absent_long_enough:
                self._vacation_active = True
        elif not self.vacation_mode_enabled and not self._vacation_manual:
            self._absence_start = None
            self._vacation_active = False

        min_temp = self._opt(OPT_VACATION_MIN_TEMP, DEFAULT_VACATION_MIN_TEMP)

        # 4. Boost — very large solar surplus; skip during vacation
        boost_threshold = self._opt(OPT_BOOST_THRESHOLD_W, DEFAULT_BOOST_THRESHOLD_W)
        boost_temp = self._opt(OPT_BOOST_TEMP, DEFAULT_BOOST_TEMP)
        if (
            self.boost_mode_enabled
            and not self._vacation_active
            and surplus_w is not None
            and surplus_w >= boost_threshold
            and (boiler_temp is None or boiler_temp < boost_temp - self._effective_hysteresis())
        ):
            return MODE_BOOST, boost_temp

        # 5. Solar — moderate surplus; during vacation cap target to min_temp (free energy)
        solar_threshold = self._opt(OPT_SOLAR_THRESHOLD_W, DEFAULT_SOLAR_THRESHOLD_W)
        solar_target = min_temp if self._vacation_active else normal_temp
        if (
            self.solar_mode_enabled
            and surplus_w is not None
            and surplus_w >= solar_threshold
            and (boiler_temp is None or boiler_temp < solar_target - self._effective_hysteresis())
        ):
            return MODE_SOLAR, solar_target

        # 6. Deadline-aware price + schedule (merged) — skip during vacation
        if self.price_mode_enabled and not self._vacation_active:
            predictive = self._opt(OPT_PREDICTIVE_HEATING, DEFAULT_PREDICTIVE_HEATING)
            skip_predictive = predictive and self._weather_forecast_tomorrow_sunny()
            result = self._decide_price_schedule(now, boiler_temp, normal_temp, skip_predictive)
            if result is not None:
                return result

        # 7. Vacation — hold minimum temperature
        if self._vacation_active:
            if boiler_temp is None or boiler_temp < min_temp - self._effective_hysteresis():
                return MODE_VACATION, min_temp

        return MODE_IDLE, normal_temp

    def _is_legionella_time(self, now: datetime) -> bool:
        ll_day = int(self._opt(OPT_LEGIONELLA_DAY, DEFAULT_LEGIONELLA_DAY))
        ll_hour = int(self._opt(OPT_LEGIONELLA_HOUR, DEFAULT_LEGIONELLA_HOUR))
        if now.weekday() != ll_day or now.hour != ll_hour:
            return False
        if self._last_legionella_run is not None and (now - self._last_legionella_run).days < 6:
            return False
        return True

    def _calc_next_heating(self, now: datetime) -> datetime | None:
        if self._vacation_active or not self.price_mode_enabled:
            return None
        schedules = self.entry.options.get(CONF_SHOWER_SCHEDULES, [])
        if not schedules:
            return None

        boiler_temp = self._state_float(self.cfg.get(CONF_BOILER_TEMP_SENSOR))
        heat_up_min = mean(self._heat_up_samples) if self._heat_up_samples else 60.0
        normal_temp = self._opt(OPT_NORMAL_TEMP, DEFAULT_NORMAL_TEMP)
        preheat_temp = self._opt(OPT_PREHEAT_TEMP, DEFAULT_PREHEAT_TEMP)
        candidates: list[datetime] = []

        for shower_dt, required_temp in self._upcoming_showers(now, schedules, normal_temp):
            hours_until = (shower_dt - now).total_seconds() / 3600

            # Skip entirely if boiler already at required_temp
            if boiler_temp is not None and boiler_temp >= required_temp - self._effective_hysteresis():
                continue

            use_preheat = preheat_temp < required_temp and hours_until > 12.0

            # Phase 1: preheat if shower is far and preheat not yet reached
            if use_preheat and (boiler_temp is None or boiler_temp < preheat_temp - self._effective_hysteresis()):
                slots = self._planned_slots_for_deadline(now, shower_dt, preheat_temp, heat_up_min, boiler_temp)
                if slots:
                    future = [s for s in slots if s > now]
                    candidates.append(min(future) if future else now)
                else:
                    fallback = shower_dt - timedelta(minutes=heat_up_min + 10)
                    if fallback > now:
                        candidates.append(fallback)

            # Phase 2: final push to required_temp within 12h window
            phase2_start = max(now, shower_dt - timedelta(hours=12))
            if phase2_start < shower_dt - timedelta(minutes=heat_up_min):
                slots2 = self._planned_slots_for_deadline(
                    phase2_start, shower_dt, required_temp, heat_up_min, boiler_temp
                )
                if slots2:
                    future2 = [s for s in slots2 if s > now]
                    if future2:
                        candidates.append(min(future2))
                else:
                    fallback = shower_dt - timedelta(minutes=heat_up_min + 10)
                    if fallback > now:
                        candidates.append(fallback)

        return min(candidates) if candidates else None

    def _calc_planned_slots(self, now: datetime) -> list[str]:
        """Return ISO timestamps of all planned heating slots across upcoming shower deadlines."""
        if self._vacation_active or not self.price_mode_enabled:
            return []
        schedules = self.entry.options.get(CONF_SHOWER_SCHEDULES, [])
        if not schedules:
            return []

        boiler_temp = self._state_float(self.cfg.get(CONF_BOILER_TEMP_SENSOR))
        heat_up_min = mean(self._heat_up_samples) if self._heat_up_samples else 60.0
        normal_temp = self._opt(OPT_NORMAL_TEMP, DEFAULT_NORMAL_TEMP)
        preheat_temp = self._opt(OPT_PREHEAT_TEMP, DEFAULT_PREHEAT_TEMP)
        all_slots: set[str] = set()

        for shower_dt, required_temp in self._upcoming_showers(now, schedules, normal_temp):
            hours_until = (shower_dt - now).total_seconds() / 3600

            if boiler_temp is not None and boiler_temp >= required_temp - self._effective_hysteresis():
                continue

            use_preheat = preheat_temp < required_temp and hours_until > 12.0

            # Phase 1: preheat slots
            if use_preheat and (boiler_temp is None or boiler_temp < preheat_temp - self._effective_hysteresis()):
                for slot in self._planned_slots_for_deadline(now, shower_dt, preheat_temp, heat_up_min, boiler_temp):
                    all_slots.add(slot.isoformat())

            # Phase 2: final-push slots within 12h window
            phase2_start = max(now, shower_dt - timedelta(hours=12))
            if phase2_start < shower_dt - timedelta(minutes=heat_up_min):
                for slot in self._planned_slots_for_deadline(phase2_start, shower_dt, required_temp, heat_up_min, boiler_temp):
                    all_slots.add(slot.isoformat())

        return sorted(all_slots)

    # ------------------------------------------------------------------
    # Hardware control
    # ------------------------------------------------------------------

    async def _apply_control(
        self,
        mode: str,
        desired_temp: float,
        boiler_temp: float | None,
        power_w: float | None,
        meter_kwh: float | None,
        now: datetime,
    ) -> None:
        should_heat = mode != MODE_IDLE

        # Anti-short-cycle: don't switch within MIN_CYCLE_MINUTES
        if self._last_switch_time is not None:
            if (now - self._last_switch_time).total_seconds() / 60 < MIN_CYCLE_MINUTES:
                return

        prev_mode = self._active_mode
        self._active_mode = mode

        if should_heat != self._heating:
            self._heating = should_heat
            self._last_switch_time = now

            if should_heat:
                await self._set_target_temp(desired_temp)
                await self._turn_on_heatpump()
                await self._set_eheater(mode == MODE_BOOST, desired_temp)
                self._session_start = now
                self._session_start_temp = boiler_temp
                self._session_start_meter = meter_kwh
                self._energy_meter_prev = meter_kwh
                self._last_session = {"running_kwh": 0.0, "running_cost": 0.0}
                self._session_notified = False
                _LOGGER.info("DHW: start heating mode=%s target=%.1f°C", mode, desired_temp)
                await self._notify(f"Boiler verwarming gestart ({mode}), doel: {desired_temp:.0f}°C")
            else:
                await self._turn_off_heatpump()
                _LOGGER.info("DHW: stop heating previous_mode=%s", prev_mode)
                self._last_session["running_kwh"] = 0.0
                self._last_session["running_cost"] = 0.0
                if prev_mode == MODE_LEGIONELLA:
                    self._last_legionella_run = now
                    await self._notify("Legionella preventie run voltooid.")
                if prev_mode == MODE_ANTI_BLOCK:
                    self._last_pump_run = now

        elif should_heat and mode != prev_mode:
            # Mode changed while heating — update target temp and eheater state only
            # when values actually change, to prevent rapid service calls on sensor flapping.
            if desired_temp != self._last_set_temp:
                await self._set_target_temp(desired_temp)
            if mode == MODE_BOOST:
                await self._set_eheater(True, desired_temp)
            elif prev_mode == MODE_BOOST:
                await self._set_eheater(False)

        # After boost: restore normal temp
        if prev_mode == MODE_BOOST and mode == MODE_IDLE:
            await self._set_target_temp(self._opt(OPT_NORMAL_TEMP, DEFAULT_NORMAL_TEMP))

        if self._heating:
            self._last_pump_run = now

    async def _set_target_temp(self, temp: float) -> None:
        entity_id = self.cfg.get(CONF_TARGET_TEMP_ENTITY)
        if not entity_id:
            return

        # Clamp to entity min/max so we never send an out-of-range value
        state = self.hass.states.get(entity_id)
        if state:
            try:
                min_val = float(state.attributes.get("min", 0))
                max_val = float(state.attributes.get("max", 100))
                clamped = max(min_val, min(max_val, temp))
                if clamped != temp:
                    _LOGGER.warning(
                        "DHW: target temp %.1f°C clamped to %.1f°C (entity range %.1f–%.1f)",
                        temp, clamped, min_val, max_val,
                    )
                temp = clamped
            except (TypeError, ValueError):
                pass

        domain = entity_id.split(".")[0]
        try:
            await self.hass.services.async_call(
                domain, "set_value", {"entity_id": entity_id, "value": temp}, blocking=True
            )
            self._last_set_temp = temp
        except Exception as err:
            _LOGGER.warning("DHW: kon doeltemperatuur niet instellen op %s: %s", entity_id, err)

    async def _set_eheater(self, active: bool, temp: float = 0.0) -> None:
        """Turn the electric heater on or off, and set its setpoint when activating."""
        sw = self.cfg.get(CONF_EHEATER_SWITCH)
        if not sw:
            return
        service = "turn_on" if active else "turn_off"
        await self.hass.services.async_call(
            "homeassistant", service, {"entity_id": sw}, blocking=True
        )
        if active:
            setpoint = self.cfg.get(CONF_EHEATER_SETPOINT_ENTITY)
            if setpoint:
                try:
                    await self.hass.services.async_call(
                        setpoint.split(".")[0],
                        "set_value",
                        {"entity_id": setpoint, "value": temp},
                        blocking=True,
                    )
                except Exception as err:
                    _LOGGER.warning("DHW: kon eheater setpoint niet instellen op %s: %s", setpoint, err)

    async def _turn_on_heatpump(self) -> None:
        sw = self.cfg.get(CONF_HEATPUMP_SWITCH)
        if sw:
            await self.hass.services.async_call(
                "homeassistant", "turn_on", {"entity_id": sw}, blocking=True
            )

    async def _turn_off_heatpump(self) -> None:
        for key in (CONF_HEATPUMP_SWITCH, CONF_EHEATER_SWITCH):
            sw = self.cfg.get(key)
            if sw:
                await self.hass.services.async_call(
                    "homeassistant", "turn_off", {"entity_id": sw}, blocking=True
                )

    # ------------------------------------------------------------------
    # Session tracking + COP calculation
    # ------------------------------------------------------------------

    async def _track_session(
        self,
        boiler_temp: float | None,
        power_w: float | None,
        price_eur: float | None,
        outside_temp: float | None,
        meter_kwh: float | None,
        now: datetime,
        desired_temp: float = 0.0,
    ) -> None:
        if not self._heating or self._session_start is None:
            return

        if meter_kwh is not None and self._energy_meter_prev is not None:
            kwh_delta = max(0.0, meter_kwh - self._energy_meter_prev)
        else:
            kwh_delta = (power_w or 0) * UPDATE_INTERVAL / 3_600_000
        cost_delta = kwh_delta * (price_eur or 0)
        _LOGGER.debug(
            "DHW session tick: kwh_delta=%.4f cost_delta=%.5f price=%.4f monthly_cost_before=%.4f",
            kwh_delta, cost_delta, price_eur or 0, self._monthly_cost,
        )

        self._monthly_kwh += kwh_delta
        self._monthly_cost += cost_delta
        self._yearly_kwh += kwh_delta
        self._yearly_cost += cost_delta

        sess = self._last_session
        sess["running_kwh"] = sess.get("running_kwh", 0.0) + kwh_delta
        sess["running_cost"] = sess.get("running_cost", 0.0) + cost_delta
        sess["kwh"] = sess["running_kwh"]
        sess["cost"] = round(sess["running_cost"], 3)

        # COP = thermal energy delivered / electrical energy consumed
        # Thermal energy: Q = volume [L] * 1 kg/L * Cp [kJ/(kg·°C)] * ΔT / 3600 → kWh
        tank_vol = self._opt(OPT_TANK_VOLUME_L, DEFAULT_TANK_VOLUME_L)
        start_temp = self._session_start_temp
        if (
            boiler_temp is not None
            and start_temp is not None
            and sess["running_kwh"] > 0
            and boiler_temp > start_temp
        ):
            thermal_kwh = tank_vol * WATER_SPECIFIC_HEAT_KJ * (boiler_temp - start_temp) / 3600
            sess["cop"] = round(thermal_kwh / sess["running_kwh"], 2)

        # Session complete when boiler reaches the active target temperature.
        # Use desired_temp (actual mode target) so legionella/boost runs don't
        # fire prematurely at normal_temp while still heating toward a higher goal.
        target_temp = desired_temp if desired_temp > 0 else self._opt(OPT_NORMAL_TEMP, DEFAULT_NORMAL_TEMP)
        if (
            not self._session_notified
            and boiler_temp is not None
            and boiler_temp >= target_temp - self._effective_hysteresis()
        ):
            self._session_notified = True
            duration_min = (now - self._session_start).total_seconds() / 60
            self._heat_up_samples.append(duration_min)
            if len(self._heat_up_samples) > HEAT_UP_SAMPLE_SIZE:
                self._heat_up_samples.pop(0)

            # Track heating rate (°C/hour) for dynamic cheap-hours calculation
            start_temp = self._session_start_temp
            if start_temp is not None and boiler_temp > start_temp and duration_min > 0:
                delta_t = boiler_temp - start_temp
                rate = delta_t / (duration_min / 60)
                if 1.0 <= rate <= 50.0:
                    self._heat_rate_samples.append(rate)
                    if len(self._heat_rate_samples) > HEAT_UP_SAMPLE_SIZE:
                        self._heat_rate_samples.pop(0)

            final_cop = sess.get("cop")
            if final_cop:
                self._cop_samples.append(final_cop)
                if len(self._cop_samples) > HEAT_UP_SAMPLE_SIZE:
                    self._cop_samples.pop(0)

            cop_str = f", COP {final_cop:.1f}" if final_cop else ""
            outside_str = f" (buiten {outside_temp:.0f}°C)" if outside_temp is not None else ""
            await self._notify(
                f"Boiler klaar: {sess['running_kwh']:.2f} kWh, "
                f"€{sess['running_cost']:.2f} kosten"
                f"{cop_str}{outside_str}"
            )
            _LOGGER.debug(
                "DHW session: %.2f kWh, €%.3f, COP=%s, %.1f min heat-up",
                sess["running_kwh"], sess["running_cost"], final_cop, duration_min,
            )

    # ------------------------------------------------------------------
    # Shower readiness warning
    # ------------------------------------------------------------------

    async def _check_shower_readiness(self, now: datetime, boiler_temp: float | None) -> None:
        """Warn via push if water won't reach temperature before a scheduled shower."""
        if boiler_temp is None or not self._heat_up_samples:
            return

        heat_up_min = mean(self._heat_up_samples)
        normal_temp = self._opt(OPT_NORMAL_TEMP, DEFAULT_NORMAL_TEMP)
        schedules = self.entry.options.get(CONF_SHOWER_SCHEDULES, [])

        for sched in schedules:
            days = sched.get("days", list(range(7)))
            if now.weekday() not in days:
                continue

            shower_time = dt_time.fromisoformat(sched.get("time", "07:30"))
            required_temp = sched.get("temp", normal_temp)
            shower_dt = now.replace(
                hour=shower_time.hour, minute=shower_time.minute, second=0, microsecond=0
            )
            if shower_dt < now:
                shower_dt += timedelta(days=1)

            minutes_until = (shower_dt - now).total_seconds() / 60
            key = shower_dt.isoformat()

            # Warning window: 10–90 min before shower
            if not (10 < minutes_until < 90):
                self._shower_warning_sent.discard(key)
                continue

            if key in self._shower_warning_sent:
                continue

            if boiler_temp < required_temp - TEMP_HYSTERESIS and minutes_until < heat_up_min:
                self._shower_warning_sent.add(key)
                await self._notify(
                    f"⚠️ Water waarschijnlijk niet op tijd warm voor "
                    f"{shower_time.strftime('%H:%M')}! "
                    f"Huidig: {boiler_temp:.0f}°C, nodig: {required_temp:.0f}°C, "
                    f"verwachte opwarmtijd: {heat_up_min:.0f} min."
                )

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    async def _notify(self, message: str) -> None:
        service = self.cfg.get(CONF_NOTIFY_SERVICE)
        if not service:
            return
        parts = service.split(".")
        if len(parts) != 2:
            return
        try:
            await self.hass.services.async_call(
                parts[0], parts[1],
                {"message": message, "title": "Warmtepomp Boiler"},
                blocking=False,
            )
        except Exception as err:
            _LOGGER.warning("DHW notify failed: %s", err)

    # ------------------------------------------------------------------
    # Status text
    # ------------------------------------------------------------------

    def _build_status_text(
        self,
        boiler_temp: float | None,
        surplus_w: float | None,
        price_eur: float | None,
        outside_temp: float | None,
        desired_temp: float | None = None,
    ) -> str:
        mode = self._active_mode
        outside = f" · buiten {outside_temp:.0f}°C" if outside_temp is not None else ""
        target = f" → {desired_temp:.0f}°C" if desired_temp is not None else ""
        if mode == MODE_IDLE:
            if self._vacation_active:
                min_temp = self._opt(OPT_VACATION_MIN_TEMP, DEFAULT_VACATION_MIN_TEMP)
                return f"Vakantie — minimum {min_temp:.0f}°C{outside}"
            return f"Standby{outside}"
        if mode == MODE_SOLAR:
            return f"Zonne-energie ({surplus_w:.0f} W overschot){target}{outside}" if surplus_w else f"Zonne-energie{target}{outside}"
        if mode == MODE_BOOST:
            return f"Boost ({surplus_w:.0f} W overschot){target}{outside}" if surplus_w else f"Boost{target}{outside}"
        if mode == MODE_PRICE:
            return f"Lage prijs (€{price_eur:.3f}/kWh){target}{outside}" if price_eur else f"Lage prijs{target}{outside}"
        if mode == MODE_SCHEDULE:
            return f"Douche schema{target}{outside}"
        if mode == MODE_LEGIONELLA:
            leg_temp = self._opt(OPT_LEGIONELLA_TEMP, DEFAULT_LEGIONELLA_TEMP)
            return f"Legionella preventie → {leg_temp:.0f}°C"
        if mode == MODE_VACATION:
            return f"Vakantie — minimum {desired_temp:.0f}°C{outside}" if desired_temp else f"Vakantie{outside}"
        if mode == MODE_MANUAL:
            return f"Handmatig aan{target}{outside}"
        if mode == MODE_ANTI_BLOCK:
            return "Anti-blokkeer run"
        return mode.capitalize()

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def active_mode(self) -> str:
        return self._active_mode

    @property
    def next_heating(self) -> datetime | None:
        return self._next_heating

    @property
    def vacation_active(self) -> bool:
        """True als vakantie modus actief is (manueel of auto-detectie)."""
        return self._vacation_active

    @vacation_active.setter
    def vacation_active(self, value: bool) -> None:
        """Handmatige "Op vakantie" schakelaar. Presence negeert handmatige instelling."""
        self._vacation_manual = value
        self._vacation_active = value
        if not value:
            self._absence_start = None
