"""Constants for the Tri-State Cover integration."""

DOMAIN = "tri_state_cover"

CONF_SWITCH_ENTITY = "switch_entity"
CONF_TRAVEL_TIME = "travel_time"
CONF_CLOSED_SENSOR = "closed_sensor"
CONF_OPEN_SENSOR = "open_sensor"
CONF_TOGGLE_DELAY = "toggle_delay"

DEFAULT_TRAVEL_TIME = 20
DEFAULT_TOGGLE_DELAY = 0.25

# Motor states in the tri-state cycle
MOTOR_STATE_IDLE = "idle"
MOTOR_STATE_OPENING = "opening"
MOTOR_STATE_CLOSING = "closing"
