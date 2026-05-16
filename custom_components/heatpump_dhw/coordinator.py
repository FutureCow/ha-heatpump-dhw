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
    CONF_PRICE_FORECAST_SENSOR,
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
    DEFAULT_CHEAP_HOURS,
    DEFAULT_PRICE_WINDOW_HOURS,
    DEFAULT_TANK_LOSS_RATE,
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
    OPT_CHEAP_HOURS,
    OPT_PRICE_WINDOW_HOURS,
    OPT_TANK_LOSS_RATE,
    DOMAIN,
    HEAT_UP_SAMPLE_SIZE,
    MIN_CYCLE_MINUTES,
    MODE_ANTI_BLOCK,
    MODE_BOOST,
    MODE_IDLE,
    MODE_LEGIONELLA,
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
    OPT_PRICE_THRESHOLD_EUR,
    OPT_REFERENCE_PRICE_EUR,
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
        self._last_session: dict = {}

        # Persisted data (loaded from storage)
        self._heat_up_samples: list[float] = []
        self._cop_samples: list[float] = []
        self._loss_samples: list[float] = []  # °C/hour tank heat loss measurements
        self._heat_rate_samples: list[float] = []  # °C/hour heating rate measurements
        self._last_legionella_run: datetime | None = None
        self._last_pump_run: datetime | None = None
        self._monthly_savings: float = 0.0
        self._savings_month: int = datetime.now().month

        # For auto-learning heat loss rate
        self._last_idle_temp: float | None = None
        self._last_idle_time: datetime | None = None

        # Mode switches — toggled by switch entities
        self.solar_mode_enabled: bool = True
        self.price_mode_enabled: bool = True
        self.boost_mode_enabled: bool = True
        self.legionella_mode_enabled: bool = True
        self.vacation_mode_enabled: bool = False

        # Absence tracking for delayed vacation mode
        self._absence_start: datetime | None = None

        # Track sent shower warnings to avoid spam
        self._shower_warning_sent: set[str] = set()

        self._next_heating: datetime | None = None

    # ------------------------------------------------------------------
    # Setup / teardown
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        stored = await self._store.async_load() or {}
        self._heat_up_samples = stored.get("heat_up_samples", [])
        self._cop_samples = stored.get("cop_samples", [])
        self._loss_samples = stored.get("loss_samples", [])
        self._heat_rate_samples = stored.get("heat_rate_samples", [])
        raw_ll = stored.get("last_legionella_run")
        self._last_legionella_run = datetime.fromisoformat(raw_ll) if raw_ll else None
        raw_lp = stored.get("last_pump_run")
        self._last_pump_run = datetime.fromisoformat(raw_lp) if raw_lp else None
        raw_abs = stored.get("absence_start")
        self._absence_start = datetime.fromisoformat(raw_abs) if raw_abs else None
        self._monthly_savings = stored.get("monthly_savings", 0.0)
        self._savings_month = stored.get("savings_month", datetime.now().month)
        self._last_session = stored.get("last_session", {})

        opts = self.entry.options
        self.solar_mode_enabled = opts.get(OPT_SOLAR_MODE_ENABLED, True)
        self.price_mode_enabled = opts.get(OPT_PRICE_MODE_ENABLED, True)
        self.boost_mode_enabled = opts.get(OPT_BOOST_MODE_ENABLED, True)
        self.legionella_mode_enabled = opts.get(OPT_LEGIONELLA_MODE_ENABLED, True)

    async def async_shutdown(self) -> None:
        await self._save_state()

    async def _save_state(self) -> None:
        await self._store.async_save(
            {
                "heat_up_samples": self._heat_up_samples[-HEAT_UP_SAMPLE_SIZE:],
                "cop_samples": self._cop_samples[-HEAT_UP_SAMPLE_SIZE:],
                "loss_samples": self._loss_samples[-HEAT_UP_SAMPLE_SIZE:],
                "heat_rate_samples": self._heat_rate_samples[-HEAT_UP_SAMPLE_SIZE:],
                "last_legionella_run": self._last_legionella_run.isoformat() if self._last_legionella_run else None,
                "last_pump_run": self._last_pump_run.isoformat() if self._last_pump_run else None,
                "absence_start": self._absence_start.isoformat() if self._absence_start else None,
                "monthly_savings": self._monthly_savings,
                "savings_month": self._savings_month,
                "last_session": self._last_session,
            }
        )

    # ------------------------------------------------------------------
    # Options / config helpers
    # ------------------------------------------------------------------

    def _opt(self, key: str, default):
        return self.entry.options.get(key, default)

    @property
    def cfg(self):
        return self.entry.data

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

        boiler_temp = self._state_float(self.cfg.get(CONF_BOILER_TEMP_SENSOR))
        power_w = self._state_float(self.cfg.get(CONF_POWER_SENSOR))
        surplus_w = self._state_float(self.cfg.get(CONF_PV_SURPLUS_SENSOR))
        price_eur = self._state_float(self.cfg.get(CONF_DYNAMIC_PRICE_SENSOR))
        outside_temp = self._state_float(self.cfg.get(CONF_OUTSIDE_TEMP_SENSOR))
        present = self._state_bool(self.cfg.get(CONF_PRESENCE_SENSOR))

        desired_mode, desired_temp = self._decide_mode(
            now, boiler_temp, surplus_w, price_eur, present
        )

        await self._apply_control(desired_mode, desired_temp, boiler_temp, power_w, now)
        await self._track_session(boiler_temp, power_w, price_eur, outside_temp, now)
        self._learn_heat_loss(boiler_temp, now)
        await self._check_shower_readiness(now, boiler_temp)

        self._next_heating = self._calc_next_heating(now)

        if now.month != self._savings_month:
            self._monthly_savings = 0.0
            self._savings_month = now.month

        await self._save_state()

        return {
            "boiler_temp": boiler_temp,
            "power_w": power_w,
            "surplus_w": surplus_w,
            "price_eur": price_eur,
            "outside_temp": outside_temp,
            "active_mode": self._active_mode,
            "heating": self._heating,
            "session_kwh": self._last_session.get("kwh", 0.0),
            "session_cost": self._last_session.get("cost", 0.0),
            "session_savings": self._last_session.get("savings", 0.0),
            "session_cop": self._last_session.get("cop"),
            "avg_cop": mean(self._cop_samples) if self._cop_samples else None,
            "next_heating": self._next_heating.isoformat() if self._next_heating else None,
            "heat_up_duration_min": round(mean(self._heat_up_samples)) if self._heat_up_samples else None,
            "monthly_savings": self._monthly_savings,
            "learned_loss_rate": round(mean(self._loss_samples), 2) if self._loss_samples else None,
            "learned_heat_rate": round(mean(self._heat_rate_samples), 1) if self._heat_rate_samples else None,
            "status_text": self._build_status_text(boiler_temp, surplus_w, price_eur, outside_temp),
        }

    def _learn_heat_loss(self, boiler_temp: float | None, now: datetime) -> None:
        """Measure tank heat loss rate during idle periods and update rolling average."""
        if self._heating or boiler_temp is None:
            self._last_idle_temp = None
            self._last_idle_time = None
            return

        if self._last_idle_temp is not None and self._last_idle_time is not None:
            elapsed_hours = (now - self._last_idle_time).total_seconds() / 3600
            if 0.1 <= elapsed_hours <= 2.0:
                drop = self._last_idle_temp - boiler_temp
                if drop > 0:
                    rate = drop / elapsed_hours
                    if 0.05 <= rate <= 3.0:  # sanity bounds
                        self._loss_samples.append(rate)
                        if len(self._loss_samples) > HEAT_UP_SAMPLE_SIZE:
                            self._loss_samples.pop(0)

        self._last_idle_temp = boiler_temp
        self._last_idle_time = now

    # ------------------------------------------------------------------
    # Price forecast helpers
    # ------------------------------------------------------------------

    def _get_forecast_prices(self, now: datetime, hours: int = 24) -> list[tuple[datetime, float]]:
        """Return (hour_dt, price) pairs for the next 24h from the forecast sensor.

        Supports three attribute formats:
        - Zonneplan app:      forecast [{datetime, electricity_price (millionths €)}]
        - Zonneplan template: prices_today/prices_tomorrow [{time, price}]
        - Nordpool:           raw_today/raw_tomorrow [{start, value}]
        """
        entity_id = self.cfg.get(CONF_PRICE_FORECAST_SENSOR)
        if not entity_id:
            return []
        state = self.hass.states.get(entity_id)
        if not state:
            return []

        attrs = state.attributes
        raw_entries: list[dict] = []

        # Zonneplan app format: attribute "forecast" with {datetime, electricity_price} entries.
        # electricity_price is in millionths of a euro (e.g. 3201888 = €0.320/kWh).
        zonneplan_forecast = attrs.get("forecast", [])
        if isinstance(zonneplan_forecast, str):
            try:
                zonneplan_forecast = json.loads(zonneplan_forecast)
            except (json.JSONDecodeError, ValueError):
                zonneplan_forecast = []
        if isinstance(zonneplan_forecast, list) and zonneplan_forecast:
            for entry in zonneplan_forecast:
                if "datetime" in entry and "electricity_price" in entry:
                    raw_entries.append({
                        "time": entry["datetime"],
                        "price": float(entry["electricity_price"]) / 1_000_000,
                    })

        # Zonneplan template format: prices_today / prices_tomorrow with {time, price}
        if not raw_entries:
            for key in ("prices_today", "prices_tomorrow"):
                val = attrs.get(key, [])
                if isinstance(val, str):
                    try:
                        val = json.loads(val)
                    except (json.JSONDecodeError, ValueError):
                        continue
                if isinstance(val, list):
                    raw_entries.extend(val)

        # Nordpool format — normalise to {time, price}
        if not raw_entries:
            for key in ("raw_today", "raw_tomorrow"):
                val = attrs.get(key, [])
                if isinstance(val, str):
                    try:
                        val = json.loads(val)
                    except (json.JSONDecodeError, ValueError):
                        continue
                if isinstance(val, list):
                    for entry in val:
                        if "start" in entry and "value" in entry:
                            raw_entries.append({"time": entry["start"], "price": entry["value"]})

        cutoff = now + timedelta(hours=hours)
        result: list[tuple[datetime, float]] = []
        for entry in raw_entries:
            try:
                t = datetime.fromisoformat(str(entry.get("time", "")).replace("Z", "+00:00"))
                if t.tzinfo is None and now.tzinfo is not None:
                    t = t.replace(tzinfo=now.tzinfo)
                p = float(entry.get("price", 0))
                if now <= t < cutoff:
                    result.append((t, p))
            except (ValueError, TypeError):
                continue

        return sorted(result, key=lambda x: x[0])

    def _needed_cheap_hours(self, boiler_temp: float | None, target_temp: float) -> int:
        """Calculate how many cheap hours are needed based on learned heating rate."""
        if boiler_temp is None or boiler_temp >= target_temp - TEMP_HYSTERESIS:
            return 0
        if self._heat_rate_samples:
            rate = mean(self._heat_rate_samples)  # °C/hour
            return max(1, math.ceil((target_temp - boiler_temp) / rate))
        # Fallback to configured value before enough data is learned
        configured = int(self._opt(OPT_CHEAP_HOURS, DEFAULT_CHEAP_HOURS))
        return configured if configured > 0 else DEFAULT_CHEAP_HOURS

    def _effective_window_hours(self) -> int:
        """Return the configured price window; 0 means use all available data (168h)."""
        w = int(self._opt(OPT_PRICE_WINDOW_HOURS, DEFAULT_PRICE_WINDOW_HOURS))
        return 168 if w == 0 else w

    def _is_cheap_hour(self, now: datetime, boiler_temp: float | None) -> bool:
        """Return True if current hour is among the cheapest N hours in the price window."""
        normal_temp = self._opt(OPT_NORMAL_TEMP, DEFAULT_NORMAL_TEMP)
        n = self._needed_cheap_hours(boiler_temp, normal_temp)
        if n == 0:
            return False
        prices = self._get_forecast_prices(now, hours=self._effective_window_hours())
        if not prices:
            return False
        cheapest = sorted(prices, key=lambda x: x[1])[:n]
        current_hour = now.replace(minute=0, second=0, microsecond=0)
        cheapest_starts = {
            dt.replace(minute=0, second=0, microsecond=0) for dt, _ in cheapest
        }
        return current_hour in cheapest_starts

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
            if boiler_temp is None or boiler_temp < leg_temp - TEMP_HYSTERESIS:
                return MODE_LEGIONELLA, leg_temp

        # 3. Boost — very large solar surplus
        boost_threshold = self._opt(OPT_BOOST_THRESHOLD_W, DEFAULT_BOOST_THRESHOLD_W)
        boost_temp = self._opt(OPT_BOOST_TEMP, DEFAULT_BOOST_TEMP)
        if (
            self.boost_mode_enabled
            and surplus_w is not None
            and surplus_w >= boost_threshold
            and (boiler_temp is None or boiler_temp < boost_temp - TEMP_HYSTERESIS)
        ):
            return MODE_BOOST, boost_temp

        # 4. Solar — moderate surplus
        solar_threshold = self._opt(OPT_SOLAR_THRESHOLD_W, DEFAULT_SOLAR_THRESHOLD_W)
        if (
            self.solar_mode_enabled
            and surplus_w is not None
            and surplus_w >= solar_threshold
            and (boiler_temp is None or boiler_temp < normal_temp - TEMP_HYSTERESIS)
        ):
            return MODE_SOLAR, normal_temp

        # 5. Dynamic price — use cheapest-hours forecast when available, else threshold
        predictive = self._opt(OPT_PREDICTIVE_HEATING, DEFAULT_PREDICTIVE_HEATING)
        skip_predictive = predictive and self._weather_forecast_tomorrow_sunny()
        if (
            self.price_mode_enabled
            and not skip_predictive
            and (boiler_temp is None or boiler_temp < normal_temp - TEMP_HYSTERESIS)
        ):
            price_threshold = self._opt(OPT_PRICE_THRESHOLD_EUR, DEFAULT_PRICE_THRESHOLD_EUR)
            use_forecast = self._is_cheap_hour(now, boiler_temp)
            use_threshold = not use_forecast and price_eur is not None and price_eur <= price_threshold
            if use_forecast or use_threshold:
                return MODE_PRICE, normal_temp

        # 6. Shower schedule — pre-heat before planned shower
        schedule_mode, schedule_temp = self._check_schedule(now, boiler_temp)
        if schedule_mode:
            return MODE_SCHEDULE, schedule_temp or normal_temp

        # 7. Vacation — hold minimum temperature after prolonged absence
        absence_hours = self._opt(OPT_VACATION_ABSENCE_HOURS, DEFAULT_VACATION_ABSENCE_HOURS)
        if present is True:
            self._absence_start = None  # reset on arrival
        elif present is False and not self.vacation_mode_enabled:
            if self._absence_start is None:
                self._absence_start = now
        absent_long_enough = (
            self._absence_start is not None
            and (now - self._absence_start).total_seconds() / 3600 >= absence_hours
        )
        if self.vacation_mode_enabled or absent_long_enough:
            min_temp = self._opt(OPT_VACATION_MIN_TEMP, DEFAULT_VACATION_MIN_TEMP)
            if boiler_temp is None or boiler_temp < min_temp - TEMP_HYSTERESIS:
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

    def _find_optimal_shower_slot(
        self,
        now: datetime,
        shower_dt: datetime,
        required_temp: float,
        heat_up_min: float,
        boiler_temp: float | None = None,
    ) -> tuple[datetime | None, float]:
        """Find cheapest hour to pre-heat for a shower, with heat-loss buffer.

        Returns (slot_start, target_temp) or (None, required_temp) if no forecast.
        """
        window_hours = self._effective_window_hours()
        loss_rate = mean(self._loss_samples) if self._loss_samples else float(self._opt(OPT_TANK_LOSS_RATE, DEFAULT_TANK_LOSS_RATE))
        boost_temp = self._opt(OPT_BOOST_TEMP, DEFAULT_BOOST_TEMP)

        all_prices = self._get_forecast_prices(now, hours=window_hours)
        if not all_prices:
            return None, required_temp

        # Slots feasible for shower pre-heat (heating finishes before shower)
        feasible = [
            (t, p) for t, p in all_prices
            if t >= now and t + timedelta(minutes=heat_up_min) <= shower_dt
        ]
        if not feasible:
            return None, required_temp

        # Calculate needed hours dynamically; fall back to configured value
        cheap_n = self._needed_cheap_hours(boiler_temp, required_temp)
        cheapest_times = {
            t for t, _ in sorted(all_prices, key=lambda x: x[1])[:cheap_n]
        }

        # Prefer the LAST cheap slot before the shower — buffer only needed for that gap.
        # If no cheap slot is feasible, fall back to the single cheapest feasible slot.
        cheap_feasible = [(t, p) for t, p in feasible if t in cheapest_times]
        if cheap_feasible:
            best_t = max(t for t, _ in cheap_feasible)  # latest cheap slot
        else:
            best_t, _ = min(feasible, key=lambda x: x[1])  # cheapest feasible

        # Buffer only for the gap between end of LAST heating and shower
        heat_end = best_t + timedelta(minutes=heat_up_min)
        hours_gap = max(0.0, (shower_dt - heat_end).total_seconds() / 3600)
        buffer = min(hours_gap * loss_rate, 8.0)  # cap at 8 °C
        target = round(min(required_temp + buffer, boost_temp), 1)

        return best_t, target

    def _check_schedule(
        self, now: datetime, boiler_temp: float | None
    ) -> tuple[bool, float | None]:
        schedules = self.entry.options.get(CONF_SHOWER_SCHEDULES, [])
        heat_up_min = mean(self._heat_up_samples) if self._heat_up_samples else 60.0
        normal_temp = self._opt(OPT_NORMAL_TEMP, DEFAULT_NORMAL_TEMP)
        window_hours = self._effective_window_hours()

        for sched in schedules:
            days = sched.get("days", list(range(7)))
            shower_time = dt_time.fromisoformat(sched.get("time", "07:30"))
            required_temp = sched.get("temp", normal_temp)

            # Collect all shower occurrences within the look-ahead window
            for day_offset in range(int(window_hours / 24) + 2):
                candidate = now + timedelta(days=day_offset)
                if candidate.weekday() not in days:
                    continue
                shower_dt = datetime.combine(candidate.date(), shower_time, tzinfo=now.tzinfo)
                if shower_dt <= now:
                    continue
                if (shower_dt - now).total_seconds() / 3600 > window_hours:
                    continue

                # Try price-optimal slot first
                optimal_t, target_temp = self._find_optimal_shower_slot(
                    now, shower_dt, required_temp, heat_up_min, boiler_temp
                )
                if optimal_t is not None:
                    current_hour = now.replace(minute=0, second=0, microsecond=0)
                    slot_hour = optimal_t.replace(minute=0, second=0, microsecond=0)
                    if current_hour == slot_hour:
                        if boiler_temp is None or boiler_temp < target_temp - TEMP_HYSTERESIS:
                            return True, target_temp
                else:
                    # No forecast — fall back to fixed window
                    start_at = shower_dt - timedelta(minutes=heat_up_min + 10)
                    if start_at <= now <= shower_dt:
                        if boiler_temp is None or boiler_temp < required_temp - TEMP_HYSTERESIS:
                            return True, required_temp

        return False, None

    def _calc_next_heating(self, now: datetime) -> datetime | None:
        schedules = self.entry.options.get(CONF_SHOWER_SCHEDULES, [])
        heat_up_min = mean(self._heat_up_samples) if self._heat_up_samples else 60.0
        normal_temp = self._opt(OPT_NORMAL_TEMP, DEFAULT_NORMAL_TEMP)
        window_hours = self._effective_window_hours()
        candidates: list[datetime] = []

        for sched in schedules:
            days = sched.get("days", list(range(7)))
            shower_time = dt_time.fromisoformat(sched.get("time", "07:30"))
            required_temp = sched.get("temp", normal_temp)

            for day_offset in range(int(window_hours / 24) + 2):
                candidate = now + timedelta(days=day_offset)
                if candidate.weekday() not in days:
                    continue
                shower_dt = datetime.combine(candidate.date(), shower_time, tzinfo=now.tzinfo)
                if shower_dt <= now:
                    continue

                optimal_t, _ = self._find_optimal_shower_slot(
                    now, shower_dt, required_temp, heat_up_min
                )
                if optimal_t is not None and optimal_t > now:
                    candidates.append(optimal_t)
                else:
                    start_dt = shower_dt - timedelta(minutes=heat_up_min + 10)
                    if start_dt > now:
                        candidates.append(start_dt)
                break  # only first occurrence per schedule

        # Also consider next cheap price hour (if price mode enabled and boiler needs heating)
        if self.price_mode_enabled:
            boiler_temp = self._state_float(self.cfg.get(CONF_BOILER_TEMP_SENSOR))
            n = self._needed_cheap_hours(boiler_temp, normal_temp)
            if n > 0:
                prices = self._get_forecast_prices(now, hours=self._effective_window_hours())
                cheapest = sorted(prices, key=lambda x: x[1])[:n]
                for slot_t, _ in cheapest:
                    slot_hour = slot_t.replace(minute=0, second=0, microsecond=0)
                    if slot_hour > now:
                        candidates.append(slot_hour)
                        break

        return min(candidates) if candidates else None

    # ------------------------------------------------------------------
    # Hardware control
    # ------------------------------------------------------------------

    async def _apply_control(
        self,
        mode: str,
        desired_temp: float,
        boiler_temp: float | None,
        power_w: float | None,
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
                self._session_start = now
                self._session_start_temp = boiler_temp
                self._last_session = {"running_kwh": 0.0, "running_cost": 0.0, "running_savings": 0.0}
                _LOGGER.info("DHW: start heating mode=%s target=%.1f°C", mode, desired_temp)
                await self._notify(f"Boiler verwarming gestart ({mode}), doel: {desired_temp:.0f}°C")
            else:
                await self._turn_off_heatpump()
                _LOGGER.info("DHW: stop heating previous_mode=%s", prev_mode)
                if prev_mode == MODE_LEGIONELLA:
                    self._last_legionella_run = now
                    await self._notify("Legionella preventie run voltooid.")
                if prev_mode == MODE_ANTI_BLOCK:
                    self._last_pump_run = now

        elif should_heat and mode != prev_mode:
            # Mode changed while heating — update target temp
            await self._set_target_temp(desired_temp)

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
        except Exception as err:
            _LOGGER.warning("DHW: kon doeltemperatuur niet instellen op %s: %s", entity_id, err)

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
        now: datetime,
    ) -> None:
        if not self._heating or self._session_start is None:
            return

        kwh_delta = (power_w or 0) * UPDATE_INTERVAL / 3_600_000
        cost_delta = kwh_delta * (price_eur or 0)
        ref_price = self._opt(OPT_REFERENCE_PRICE_EUR, DEFAULT_REFERENCE_PRICE_EUR)
        savings_delta = kwh_delta * max(0.0, ref_price - (price_eur or ref_price))

        sess = self._last_session
        sess["running_kwh"] = sess.get("running_kwh", 0.0) + kwh_delta
        sess["running_cost"] = sess.get("running_cost", 0.0) + cost_delta
        sess["running_savings"] = sess.get("running_savings", 0.0) + savings_delta
        sess["kwh"] = sess["running_kwh"]
        sess["cost"] = sess["running_cost"]
        sess["savings"] = sess["running_savings"]

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

        # Session complete when boiler reaches target
        target_temp = self._opt(OPT_NORMAL_TEMP, DEFAULT_NORMAL_TEMP)
        if boiler_temp is not None and boiler_temp >= target_temp - TEMP_HYSTERESIS:
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

            self._monthly_savings += sess["running_savings"]

            cop_str = f", COP {final_cop:.1f}" if final_cop else ""
            outside_str = f" (buiten {outside_temp:.0f}°C)" if outside_temp is not None else ""
            await self._notify(
                f"Boiler klaar: {sess['running_kwh']:.2f} kWh, "
                f"€{sess['running_cost']:.2f} kosten, "
                f"besparing €{sess['running_savings']:.2f}"
                f"{cop_str}{outside_str}"
            )
            _LOGGER.debug(
                "DHW session: %.2f kWh, €%.3f, COP=%s, %.1f min heat-up",
                sess["running_kwh"], sess["running_cost"], final_cop, duration_min,
            )
            sess["running_kwh"] = 0.0
            sess["running_cost"] = 0.0
            sess["running_savings"] = 0.0

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
    ) -> str:
        mode = self._active_mode
        outside = f" · buiten {outside_temp:.0f}°C" if outside_temp is not None else ""
        if mode == MODE_IDLE:
            return f"Standby{outside}"
        if mode == MODE_SOLAR:
            return f"Zonne-energie ({surplus_w:.0f} W overschot){outside}" if surplus_w else f"Zonne-energie{outside}"
        if mode == MODE_BOOST:
            return f"Boost ({surplus_w:.0f} W overschot){outside}" if surplus_w else f"Boost{outside}"
        if mode == MODE_PRICE:
            return f"Lage prijs (€{price_eur:.3f}/kWh){outside}" if price_eur else f"Lage prijs{outside}"
        if mode == MODE_SCHEDULE:
            return f"Douche schema{outside}"
        if mode == MODE_LEGIONELLA:
            return "Legionella preventie"
        if mode == MODE_VACATION:
            return f"Vakantie modus{outside}"
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
