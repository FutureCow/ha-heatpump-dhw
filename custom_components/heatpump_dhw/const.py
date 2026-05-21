"""Constants for the Heat Pump DHW integration."""

DOMAIN = "heatpump_dhw"
PLATFORMS = ["sensor", "switch", "number"]

# Config keys — hardware sensors
CONF_BOILER_TEMP_SENSOR = "boiler_temp_sensor"
CONF_POWER_SENSOR = "power_sensor"
CONF_ENERGY_METER_SENSOR = "energy_meter_sensor"

# Config keys — hardware controls
CONF_TARGET_TEMP_ENTITY = "target_temp_entity"
CONF_HEATPUMP_SWITCH = "heatpump_switch"
CONF_EHEATER_SWITCH = "eheater_switch"
CONF_EHEATER_SETPOINT_ENTITY = "eheater_setpoint_entity"
# Config keys — grid/solar sensors
CONF_PV_SURPLUS_SENSOR = "pv_surplus_sensor"
CONF_DYNAMIC_PRICE_SENSOR = "dynamic_price_sensor"
CONF_PRICE_FORECAST_SENSOR = "price_forecast_sensor"

# Config keys — optional sensors
CONF_WEATHER_ENTITY = "weather_entity"
CONF_OUTSIDE_TEMP_SENSOR = "outside_temp_sensor"
CONF_PRESENCE_SENSOR = "presence_sensor"
CONF_NOTIFY_SERVICE = "notify_service"

# Config keys — shower schedules stored in options
CONF_SHOWER_SCHEDULES = "shower_schedules"

# Options keys — thresholds (stored in config entry options, editable after setup)
OPT_SOLAR_THRESHOLD_W = "solar_threshold_w"
OPT_BOOST_THRESHOLD_W = "boost_threshold_w"
OPT_PRICE_THRESHOLD_EUR = "price_threshold_eur"
OPT_NORMAL_TEMP = "normal_temp"
OPT_BOOST_TEMP = "boost_temp"
OPT_VACATION_MIN_TEMP = "vacation_min_temp"
OPT_LEGIONELLA_TEMP = "legionella_temp"
OPT_LEGIONELLA_DAY = "legionella_day"  # 0=Mon … 6=Sun
OPT_LEGIONELLA_HOUR = "legionella_hour"
OPT_SOLAR_MODE_ENABLED = "solar_mode_enabled"
OPT_PRICE_MODE_ENABLED = "price_mode_enabled"
OPT_BOOST_MODE_ENABLED = "boost_mode_enabled"
OPT_LEGIONELLA_MODE_ENABLED = "legionella_mode_enabled"
OPT_TANK_VOLUME_L = "tank_volume_l"
OPT_ANTI_BLOCK_DAYS = "anti_block_days"
OPT_PREDICTIVE_HEATING = "predictive_heating"  # skip price-mode if tomorrow is sunny
OPT_VACATION_ABSENCE_HOURS = "vacation_absence_hours"
OPT_CHEAP_HOURS = "cheap_hours"
OPT_PRICE_WINDOW_HOURS = "price_window_hours"
OPT_TANK_LOSS_RATE = "tank_loss_rate"
OPT_PRICE_MODE_CONSECUTIVE = "price_mode_consecutive"
OPT_BOILER_SETPOINT_OFFSET = "boiler_setpoint_offset"
OPT_PREHEAT_TEMP = "preheat_temp"

# Default option values
DEFAULT_SOLAR_THRESHOLD_W = 500
DEFAULT_BOOST_THRESHOLD_W = 2000
DEFAULT_PRICE_THRESHOLD_EUR = 0.08
DEFAULT_NORMAL_TEMP = 55.0
DEFAULT_BOOST_TEMP = 65.0
DEFAULT_VACATION_MIN_TEMP = 40.0
DEFAULT_LEGIONELLA_TEMP = 65.0
DEFAULT_LEGIONELLA_DAY = 6  # Sunday
DEFAULT_LEGIONELLA_HOUR = 13  # 13:00
DEFAULT_TANK_VOLUME_L = 200.0
DEFAULT_ANTI_BLOCK_DAYS = 3
DEFAULT_PREDICTIVE_HEATING = True
DEFAULT_VACATION_ABSENCE_HOURS = 24
DEFAULT_CHEAP_HOURS = 2
DEFAULT_PRICE_WINDOW_HOURS = 24
DEFAULT_TANK_LOSS_RATE = 0.5
DEFAULT_AMBIENT_TEMP = 18.0  # assumed ambient (°C) when no outside sensor available
DEFAULT_PRICE_MODE_CONSECUTIVE = False
DEFAULT_BOILER_SETPOINT_OFFSET = 0.0
DEFAULT_PREHEAT_TEMP = 40.0

# Heating modes
MODE_IDLE = "idle"
MODE_SOLAR = "solar"
MODE_PRICE = "price"
MODE_BOOST = "boost"
MODE_SCHEDULE = "schedule"
MODE_LEGIONELLA = "legionella"
MODE_VACATION = "vacation"
MODE_MANUAL = "manual"
MODE_ANTI_BLOCK = "anti_block"

# Storage key for persistent data
STORAGE_KEY = f"{DOMAIN}.data"
STORAGE_VERSION = 1

# How many heat-up samples to keep for rolling average
HEAT_UP_SAMPLE_SIZE = 10

# Minimum temperature considered "hot enough" to stop tracking a session
TEMP_HYSTERESIS = 1.0  # °C below target before we consider heating done

# Update interval in seconds
UPDATE_INTERVAL = 60

# Minimum minutes between switching the heatpump on/off to avoid short cycling
MIN_CYCLE_MINUTES = 5

# Anti-block run duration in minutes
ANTI_BLOCK_RUN_MINUTES = 5

# Weather condition strings considered "sunny" for predictive heating
SUNNY_CONDITIONS = {"sunny", "partlycloudy", "clear-night"}

# Specific heat of water: kJ per kg per °C
WATER_SPECIFIC_HEAT_KJ = 4.186
