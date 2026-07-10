"""Cover platform for Tri-State Cover integration."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_OFF,
)
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONF_CLOSED_SENSOR,
    CONF_OPEN_SENSOR,
    CONF_SWITCH_ENTITY,
    CONF_TOGGLE_DELAY,
    CONF_TRAVEL_TIME,
    DEFAULT_TOGGLE_DELAY,
    DEFAULT_TRAVEL_TIME,
    DOMAIN,
    MOTOR_STATE_CLOSING,
    MOTOR_STATE_IDLE,
    MOTOR_STATE_OPENING,
)

_LOGGER = logging.getLogger(__name__)

# HA device classes where ON = open, OFF = closed
_OPENING_DEVICE_CLASSES = frozenset(
    {"garage_door", "door", "opening", "window", "gate"}
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Tri-State Cover from a config entry."""
    config = {**entry.data, **entry.options}
    async_add_entities([TriStateCoverEntity(hass, entry, config)])


class TriStateCoverEntity(CoverEntity, RestoreEntity):
    """Representation of a Tri-State Cover."""

    _attr_device_class = CoverDeviceClass.GARAGE
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        config: dict[str, Any],
    ) -> None:
        """Initialize the cover."""
        self._entry = entry
        self._switch_entity: str = config[CONF_SWITCH_ENTITY]
        self._travel_time: float = config.get(CONF_TRAVEL_TIME, DEFAULT_TRAVEL_TIME)
        self._closed_sensor: str | None = config.get(CONF_CLOSED_SENSOR)
        self._open_sensor: str | None = config.get(CONF_OPEN_SENSOR)
        self._toggle_delay: float = config.get(CONF_TOGGLE_DELAY, DEFAULT_TOGGLE_DELAY)

        self._attr_unique_id = f"{DOMAIN}_{self._switch_entity}"

        # State tracking
        self._position: float = 0.0  # 0 = closed, 100 = open
        self._target_position: float | None = None
        self._motor_state: str = MOTOR_STATE_IDLE
        self._next_direction_is_open: bool = True  # Tri-state cycle tracking
        self._movement_started_at: datetime | None = None
        self._position_at_start: float = 0.0

        # Timer handle
        self._timer_unsub: CALLBACK_TYPE | None = None
        self._sensor_unsubs: list[CALLBACK_TYPE] = []

    @property
    def device_info(self):
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, self._switch_entity)},
            "name": f"Tri-State Cover ({self._switch_entity})",
            "manufacturer": "Tri-State Cover",
            "model": "Tri-State Motor",
        }

    @property
    def current_cover_position(self) -> int | None:
        """Return current position of cover (0=closed, 100=open)."""
        if self._motor_state != MOTOR_STATE_IDLE:
            return self._calculate_current_position()
        return round(self._position)

    @property
    def is_closed(self) -> bool | None:
        """Return if the cover is closed."""
        return self._position <= 0

    @property
    def is_opening(self) -> bool:
        """Return if the cover is opening."""
        return self._motor_state == MOTOR_STATE_OPENING

    @property
    def is_closing(self) -> bool:
        """Return if the cover is closing."""
        return self._motor_state == MOTOR_STATE_CLOSING

    def _calculate_current_position(self) -> int:
        """Calculate estimated position based on elapsed movement time."""
        if self._movement_started_at is None:
            return round(self._position)

        elapsed = (
            datetime.now(timezone.utc) - self._movement_started_at
        ).total_seconds()
        travel_distance = abs(
            (self._target_position if self._target_position is not None
             else (100 if self._motor_state == MOTOR_STATE_OPENING else 0))
            - self._position_at_start
        )
        if travel_distance <= 0 or self._travel_time <= 0:
            return round(self._position)

        duration_for_move = (travel_distance / 100.0) * self._travel_time
        fraction = min(elapsed / duration_for_move, 1.0)

        if self._motor_state == MOTOR_STATE_OPENING:
            target = self._target_position if self._target_position is not None else 100
            pos = self._position_at_start + fraction * (target - self._position_at_start)
        elif self._motor_state == MOTOR_STATE_CLOSING:
            target = self._target_position if self._target_position is not None else 0
            pos = self._position_at_start + fraction * (target - self._position_at_start)
        else:
            pos = self._position

        return round(max(0, min(100, pos)))

    # -- Sensor polarity helpers ------------------------------------

    def _get_sensor_device_class(self, sensor_entity: str) -> str:
        """Get the device_class of a sensor entity."""
        state = self.hass.states.get(sensor_entity)
        if state is None:
            return ""
        return state.attributes.get("device_class", "") or ""

    def _sensor_means_closed(self, sensor_entity: str, state_value: str) -> bool:
        """Check if the given state value means the door is at the closed endstop.

        For sensors with device_class in (garage_door, door, opening, ...):
            HA convention is ON=open, OFF=closed.
            So the closed endstop is reached when state is OFF.

        For other sensors (plain reed switches, etc.):
            ON = sensor triggered = endstop reached.
        """
        device_class = self._get_sensor_device_class(sensor_entity)
        if device_class in _OPENING_DEVICE_CLASSES:
            return state_value == STATE_OFF
        return state_value == STATE_ON

    def _sensor_means_not_closed(self, sensor_entity: str, state_value: str) -> bool:
        """Check if the given state value means the door is NOT at the closed endstop.

        Inverse of _sensor_means_closed.
        """
        device_class = self._get_sensor_device_class(sensor_entity)
        if device_class in _OPENING_DEVICE_CLASSES:
            return state_value == STATE_ON
        return state_value == STATE_OFF

    def _sensor_means_open(self, sensor_entity: str, state_value: str) -> bool:
        """Check if the given state value means the door is at the open endstop.

        For sensors with device_class in (garage_door, door, opening, ...):
            HA convention is ON=open, OFF=closed.
            So the open endstop is reached when state is ON.

        For other sensors (plain reed switches, etc.):
            ON = sensor triggered = endstop reached.
        """
        device_class = self._get_sensor_device_class(sensor_entity)
        if device_class in _OPENING_DEVICE_CLASSES:
            return state_value == STATE_ON
        return state_value == STATE_ON

    def _sensor_means_not_open(self, sensor_entity: str, state_value: str) -> bool:
        """Check if the given state value means the door is NOT at the open endstop."""
        device_class = self._get_sensor_device_class(sensor_entity)
        if device_class in _OPENING_DEVICE_CLASSES:
            return state_value == STATE_OFF
        return state_value == STATE_OFF

    # -- Lifecycle --------------------------------------------------

    async def async_added_to_hass(self) -> None:
        """Restore state and subscribe to sensor events."""
        await super().async_added_to_hass()

        # Restore previous state
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._position = float(
                last_state.attributes.get(ATTR_POSITION, 0)
            )
            self._next_direction_is_open = last_state.attributes.get(
                "next_direction_is_open", True
            )
            _LOGGER.debug(
                "Restored state: position=%s, next_direction_is_open=%s",
                self._position,
                self._next_direction_is_open,
            )

        # Calibrate from sensors if available
        await self._calibrate_from_sensors()

        # Subscribe to sensor state changes for live calibration
        if self._closed_sensor:
            self._sensor_unsubs.append(
                async_track_state_change_event(
                    self.hass,
                    self._closed_sensor,
                    self._handle_closed_sensor_change,
                )
            )
        if self._open_sensor:
            self._sensor_unsubs.append(
                async_track_state_change_event(
                    self.hass,
                    self._open_sensor,
                    self._handle_open_sensor_change,
                )
            )

        # Listen for config entry updates (options flow)
        self._entry.async_on_unload(
            self._entry.add_update_listener(self._async_options_updated)
        )

    async def async_will_remove_from_hass(self) -> None:
        """Clean up on removal."""
        self._cancel_timer()
        for unsub in self._sensor_unsubs:
            unsub()
        self._sensor_unsubs.clear()

    @staticmethod
    async def _async_options_updated(
        hass: HomeAssistant, entry: ConfigEntry
    ) -> None:
        """Handle options update -- reload the entry."""
        await hass.config_entries.async_reload(entry.entry_id)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes for state restoration."""
        return {
            "next_direction_is_open": self._next_direction_is_open,
            "motor_state": self._motor_state,
            "target_position": self._target_position,
        }

    # -- Motor control ----------------------------------------------

    async def _press_button(self) -> None:
        """Press the motor toggle button once (pulse the relay).

        Ensures a clean pulse by turning the switch off first if it is
        still on from a previous press, then turning it on.
        """
        switch_state = self.hass.states.get(self._switch_entity)
        if switch_state and switch_state.state == STATE_ON:
            _LOGGER.debug(
                "Switch %s is still ON -- turning off before pulse",
                self._switch_entity,
            )
            await self.hass.services.async_call(
                "switch",
                SERVICE_TURN_OFF,
                {"entity_id": self._switch_entity},
            )
            await asyncio.sleep(0.15)

        await self.hass.services.async_call(
            "switch",
            SERVICE_TURN_ON,
            {"entity_id": self._switch_entity},
        )
        _LOGGER.debug("Button pressed (switch.turn_on %s)", self._switch_entity)

    async def _triple_press(self) -> None:
        """Triple-press to reverse direction: start -> stop -> reverse."""
        _LOGGER.debug("Triple-press for direction reversal")
        await self._press_button()
        await asyncio.sleep(self._toggle_delay)
        await self._press_button()
        await asyncio.sleep(self._toggle_delay)
        await self._press_button()

    async def _start_movement(
        self, direction_open: bool, target: float
    ) -> None:
        """Start the motor in the given direction toward target position."""
        # Cancel any running timer
        self._cancel_timer()

        current_pos = self._position
        if abs(current_pos - target) < 2:
            _LOGGER.debug("Already at target (%.1f%% vs %.1f%%)", current_pos, target)
            return

        # Determine if we need to reverse direction
        if direction_open == self._next_direction_is_open:
            await self._press_button()
        else:
            await self._triple_press()

        # Update state
        self._motor_state = (
            MOTOR_STATE_OPENING if direction_open else MOTOR_STATE_CLOSING
        )
        self._next_direction_is_open = direction_open
        self._target_position = target
        self._movement_started_at = datetime.now(timezone.utc)
        self._position_at_start = current_pos

        # Calculate duration for this movement
        travel_fraction = abs(target - current_pos) / 100.0
        duration = travel_fraction * self._travel_time

        _LOGGER.info(
            "Started %s from %.1f%% to %.1f%% (%.1fs, next_dir_was=%s)",
            self._motor_state,
            current_pos,
            target,
            duration,
            "open" if direction_open else "close",
        )

        # Schedule timer to stop at target
        self._timer_unsub = self.hass.loop.call_later(
            duration, self._on_timer_finished
        )

        self.async_write_ha_state()

    @callback
    def _on_timer_finished(self) -> None:
        """Handle movement timer completion."""
        self._timer_unsub = None
        target = self._target_position

        is_partial = target is not None and target not in (0, 100)

        _LOGGER.debug(
            "Timer finished: target=%.1f%%, partial=%s, motor_state=%s",
            target if target is not None else -1,
            is_partial,
            self._motor_state,
        )

        if is_partial:
            self.hass.async_create_task(self._stop_motor_and_finalize(target))
        else:
            # Full travel -- motor auto-stops at endstop
            self._finalize_movement(target if target is not None else self._position)

    async def _stop_motor_and_finalize(self, target: float) -> None:
        """Stop the motor and finalize position for partial movements."""
        await self._press_button()
        self._finalize_movement(target)

    @callback
    def _finalize_movement(self, final_position: float) -> None:
        """Finalize movement: update position, toggle direction, reset state."""
        self._position = max(0, min(100, final_position))
        self._motor_state = MOTOR_STATE_IDLE
        self._target_position = None
        self._movement_started_at = None
        self._position_at_start = self._position

        # Toggle direction for next press (tri-state cycle)
        self._next_direction_is_open = not self._next_direction_is_open

        _LOGGER.info(
            "Movement finished at %.1f%%, next direction: %s",
            self._position,
            "open" if self._next_direction_is_open else "close",
        )

        self.async_write_ha_state()

    def _cancel_timer(self) -> None:
        """Cancel the movement timer if running."""
        if self._timer_unsub is not None:
            self._timer_unsub.cancel()
            self._timer_unsub = None

    # -- Cover actions ----------------------------------------------

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        _LOGGER.debug(
            "async_open_cover called (motor_state=%s, position=%.1f%%)",
            self._motor_state,
            self._position,
        )
        if self._motor_state != MOTOR_STATE_IDLE:
            await self.async_stop_cover()
            await asyncio.sleep(0.5)

        if self._position >= 100:
            return

        await self._start_movement(direction_open=True, target=100)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        _LOGGER.debug(
            "async_close_cover called (motor_state=%s, position=%.1f%%)",
            self._motor_state,
            self._position,
        )
        if self._motor_state != MOTOR_STATE_IDLE:
            await self.async_stop_cover()
            await asyncio.sleep(0.5)

        if self._position <= 0:
            return

        await self._start_movement(direction_open=False, target=0)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        _LOGGER.info(
            "async_stop_cover called (motor_state=%s, position=%.1f%%, "
            "movement_started_at=%s, target=%.1f%%)",
            self._motor_state,
            self._position,
            self._movement_started_at,
            self._target_position if self._target_position is not None else -1,
        )

        if self._motor_state == MOTOR_STATE_IDLE:
            _LOGGER.info("Stop requested but motor is idle -- ignoring")
            return

        # Calculate current position from elapsed time
        current = self._calculate_current_position()

        _LOGGER.info(
            "Stopping cover at calculated position %d%% (was %s)",
            current,
            self._motor_state,
        )

        # Cancel timer first to prevent race with _on_timer_finished
        self._cancel_timer()

        # Stop the motor
        await self._press_button()

        # Finalize at calculated position
        self._finalize_movement(float(current))

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the cover to a specific position."""
        target = float(kwargs[ATTR_POSITION])
        _LOGGER.debug("async_set_cover_position called: target=%.1f%%", target)

        if self._motor_state != MOTOR_STATE_IDLE:
            await self.async_stop_cover()
            await asyncio.sleep(0.5)

        direction_open = target > self._position
        await self._start_movement(direction_open=direction_open, target=target)

    # -- Sensor calibration -----------------------------------------

    async def _calibrate_from_sensors(self) -> None:
        """Calibrate position from endstop sensors on startup.

        Performs both positive and negative calibration:
        - Positive: sensor confirms endstop -> set known position
        - Negative: sensor contradicts current position -> correct it
        """
        if self._closed_sensor:
            state = self.hass.states.get(self._closed_sensor)
            if state:
                dc = state.attributes.get("device_class", "none")
                if self._sensor_means_closed(self._closed_sensor, state.state):
                    # Sensor confirms door is closed
                    self._position = 0.0
                    self._position_at_start = 0.0
                    self._next_direction_is_open = True
                    self._motor_state = MOTOR_STATE_IDLE
                    _LOGGER.info(
                        "Startup calibration: closed sensor confirms CLOSED "
                        "(%s=%s, dc=%s) -> position=0%%",
                        self._closed_sensor, state.state, dc,
                    )
                    return
                elif self._sensor_means_not_closed(
                    self._closed_sensor, state.state
                ):
                    # Sensor says door is NOT closed
                    if self._position <= 0:
                        # Position says closed but sensor disagrees -> fix it
                        self._position = 100.0
                        self._position_at_start = 100.0
                        self._next_direction_is_open = False
                        self._motor_state = MOTOR_STATE_IDLE
                        _LOGGER.info(
                            "Startup calibration: closed sensor says NOT "
                            "CLOSED but position was 0%% (%s=%s, dc=%s) "
                            "-> correcting to position=100%%",
                            self._closed_sensor, state.state, dc,
                        )
                        return
                    else:
                        _LOGGER.debug(
                            "Startup: closed sensor says NOT CLOSED, "
                            "position=%.1f%% (consistent, no correction)",
                            self._position,
                        )

        if self._open_sensor:
            state = self.hass.states.get(self._open_sensor)
            if state:
                dc = state.attributes.get("device_class", "none")
                if self._sensor_means_open(self._open_sensor, state.state):
                    self._position = 100.0
                    self._position_at_start = 100.0
                    self._next_direction_is_open = False
                    self._motor_state = MOTOR_STATE_IDLE
                    _LOGGER.info(
                        "Startup calibration: open sensor confirms OPEN "
                        "(%s=%s, dc=%s) -> position=100%%",
                        self._open_sensor, state.state, dc,
                    )
                    return
                elif self._sensor_means_not_open(
                    self._open_sensor, state.state
                ):
                    if self._position >= 100:
                        self._position = 0.0
                        self._position_at_start = 0.0
                        self._next_direction_is_open = True
                        self._motor_state = MOTOR_STATE_IDLE
                        _LOGGER.info(
                            "Startup calibration: open sensor says NOT OPEN "
                            "but position was 100%% (%s=%s, dc=%s) "
                            "-> correcting to position=0%%",
                            self._open_sensor, state.state, dc,
                        )
                        return

        _LOGGER.debug(
            "No sensor calibration change on startup "
            "(position=%.1f%%, closed=%s, open=%s)",
            self._position,
            self.hass.states.get(self._closed_sensor)
            if self._closed_sensor else "n/a",
            self.hass.states.get(self._open_sensor)
            if self._open_sensor else "n/a",
        )

    def _reset_to_position(self, position: float, next_open: bool) -> None:
        """Hard-reset cover state to a known position from sensor feedback."""
        was_moving = self._motor_state != MOTOR_STATE_IDLE
        self._cancel_timer()
        self._position = position
        self._motor_state = MOTOR_STATE_IDLE
        self._target_position = None
        self._movement_started_at = None
        self._position_at_start = position
        self._next_direction_is_open = next_open
        _LOGGER.info(
            "Sensor calibration: position=%.0f%%, was_moving=%s, next_dir=%s",
            position,
            was_moving,
            "open" if next_open else "close",
        )
        self.async_write_ha_state()

    @callback
    def _handle_closed_sensor_change(self, event: Event) -> None:
        """Handle closed sensor state change.

        Respects device_class polarity. Also enforces the invariant:
        if the sensor says 'not closed', the cover must not be at 0%.
        """
        new_state = event.data.get("new_state")
        if new_state is None:
            return

        dc = new_state.attributes.get("device_class", "none")

        if self._sensor_means_closed(self._closed_sensor, new_state.state):
            _LOGGER.info(
                "Closed sensor: door IS CLOSED (state=%s, dc=%s)",
                new_state.state, dc,
            )
            self._reset_to_position(0.0, next_open=True)

        elif self._sensor_means_not_closed(
            self._closed_sensor, new_state.state
        ):
            _LOGGER.info(
                "Closed sensor: door LEFT closed position "
                "(state=%s, dc=%s, motor_state=%s, position=%.1f%%)",
                new_state.state, dc, self._motor_state, self._position,
            )
            # INVARIANT: If sensor says not closed, position must not be 0%
            if self._position <= 0 and self._motor_state == MOTOR_STATE_IDLE:
                _LOGGER.warning(
                    "INVARIANT FIX: Position was 0%% but sensor says not "
                    "closed -> setting to 100%%"
                )
                self._reset_to_position(100.0, next_open=False)

    @callback
    def _handle_open_sensor_change(self, event: Event) -> None:
        """Handle open sensor state change.

        Respects device_class polarity. Also enforces the invariant:
        if the sensor says 'not open', the cover must not be at 100%.
        """
        new_state = event.data.get("new_state")
        if new_state is None:
            return

        dc = new_state.attributes.get("device_class", "none")

        if self._sensor_means_open(self._open_sensor, new_state.state):
            _LOGGER.info(
                "Open sensor: door IS OPEN (state=%s, dc=%s)",
                new_state.state, dc,
            )
            self._reset_to_position(100.0, next_open=False)

        elif self._sensor_means_not_open(
            self._open_sensor, new_state.state
        ):
            _LOGGER.info(
                "Open sensor: door LEFT open position "
                "(state=%s, dc=%s, motor_state=%s, position=%.1f%%)",
                new_state.state, dc, self._motor_state, self._position,
            )
            # INVARIANT: If sensor says not open, position must not be 100%
            if self._position >= 100 and self._motor_state == MOTOR_STATE_IDLE:
                _LOGGER.warning(
                    "INVARIANT FIX: Position was 100%% but sensor says not "
                    "open -> setting to 0%%"
                )
                self._reset_to_position(0.0, next_open=True)
