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
    SERVICE_TURN_ON,
    STATE_ON,
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
        self._position: float = 0.0
        self._target_position: float | None = None
        self._motor_state: str = MOTOR_STATE_IDLE
        self._next_direction_is_open: bool = True
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
        """Calculate estimated position based on elapsed time."""
        if self._movement_started_at is None:
            return round(self._position)

        elapsed = (
            datetime.now(timezone.utc) - self._movement_started_at
        ).total_seconds()
        travel = self._travel_time if self._travel_time > 0 else 1
        fraction = min(elapsed / travel, 1.0)

        if self._target_position is not None:
            target = self._target_position
        elif self._motor_state == MOTOR_STATE_OPENING:
            target = 100.0
        else:
            target = 0.0

        pos = self._position_at_start + fraction * (target - self._position_at_start)
        return round(max(0, min(100, pos)))

    async def async_added_to_hass(self) -> None:
        """Restore state and subscribe to sensor events."""
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._position = float(
                last_state.attributes.get(ATTR_POSITION, 0)
            )
            self._next_direction_is_open = last_state.attributes.get(
                "next_direction_is_open", True
            )
            _LOGGER.debug(
                "Restored: position=%s, next_open=%s",
                self._position,
                self._next_direction_is_open,
            )

        await self._calibrate_from_sensors()

        if self._closed_sensor:
            self._sensor_unsubs.append(
                async_track_state_change_event(
                    self.hass,
                    self._closed_sensor,
                    self._handle_closed_sensor,
                )
            )
        if self._open_sensor:
            self._sensor_unsubs.append(
                async_track_state_change_event(
                    self.hass,
                    self._open_sensor,
                    self._handle_open_sensor,
                )
            )

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
        """Handle options update."""
        await hass.config_entries.async_reload(entry.entry_id)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes for state restoration."""
        return {
            "next_direction_is_open": self._next_direction_is_open,
            "motor_state": self._motor_state,
            "target_position": self._target_position,
        }

    # -- Motor control --

    async def _press_button(self) -> None:
        """Press the motor toggle button once."""
        await self.hass.services.async_call(
            "switch",
            SERVICE_TURN_ON,
            {"entity_id": self._switch_entity},
        )

    async def _triple_press(self) -> None:
        """Triple-press to reverse direction."""
        await self._press_button()
        await asyncio.sleep(self._toggle_delay)
        await self._press_button()
        await asyncio.sleep(self._toggle_delay)
        await self._press_button()

    async def _start_movement(
        self, direction_open: bool, target: float
    ) -> None:
        """Start the motor toward target position."""
        self._cancel_timer()

        current_pos = self._position
        if abs(current_pos - target) < 2:
            return

        if direction_open == self._next_direction_is_open:
            await self._press_button()
        else:
            await self._triple_press()

        self._motor_state = (
            MOTOR_STATE_OPENING if direction_open else MOTOR_STATE_CLOSING
        )
        self._next_direction_is_open = direction_open
        self._target_position = target
        self._movement_started_at = datetime.now(timezone.utc)
        self._position_at_start = current_pos

        travel_fraction = abs(target - current_pos) / 100.0
        duration = travel_fraction * self._travel_time

        _LOGGER.debug(
            "Moving %s: %.0f%% -> %.0f%% (%.1fs)",
            self._motor_state, current_pos, target, duration,
        )

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
        if is_partial:
            self.hass.async_create_task(self._stop_motor_and_set(target))
        else:
            final = target if target is not None else self._position
            self._finalize_movement(final)

    async def _stop_motor_and_set(self, target: float) -> None:
        """Stop motor and finalize for partial positions."""
        await self._press_button()
        self._finalize_movement(target)

    @callback
    def _finalize_movement(self, final_position: float) -> None:
        """Set final position and toggle direction."""
        self._position = max(0, min(100, final_position))
        self._motor_state = MOTOR_STATE_IDLE
        self._target_position = None
        self._movement_started_at = None
        self._position_at_start = self._position
        self._next_direction_is_open = not self._next_direction_is_open

        _LOGGER.debug(
            "Done at %.0f%%, next: %s",
            self._position,
            "open" if self._next_direction_is_open else "close",
        )
        self.async_write_ha_state()

    def _cancel_timer(self) -> None:
        """Cancel the movement timer if running."""
        if self._timer_unsub is not None:
            self._timer_unsub.cancel()
            self._timer_unsub = None

    # -- Cover actions --

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        if self._motor_state != MOTOR_STATE_IDLE:
            await self.async_stop_cover()
            await asyncio.sleep(0.5)
        if self._position >= 100:
            return
        await self._start_movement(direction_open=True, target=100)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        if self._motor_state != MOTOR_STATE_IDLE:
            await self.async_stop_cover()
            await asyncio.sleep(0.5)
        if self._position <= 0:
            return
        await self._start_movement(direction_open=False, target=0)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        if self._motor_state == MOTOR_STATE_IDLE:
            return
        current = self._calculate_current_position()
        self._cancel_timer()
        await self._press_button()
        self._finalize_movement(float(current))

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the cover to a specific position."""
        target = float(kwargs[ATTR_POSITION])
        if self._motor_state != MOTOR_STATE_IDLE:
            await self.async_stop_cover()
            await asyncio.sleep(0.5)
        direction_open = target > self._position
        await self._start_movement(direction_open=direction_open, target=target)

    # -- Sensor calibration --

    async def _calibrate_from_sensors(self) -> None:
        """Calibrate position from endstop sensors on startup."""
        if self._closed_sensor:
            state = self.hass.states.get(self._closed_sensor)
            if state and state.state == STATE_ON:
                self._position = 0.0
                self._position_at_start = 0.0
                self._next_direction_is_open = True
                self._motor_state = MOTOR_STATE_IDLE
                _LOGGER.info("Startup calibration: closed sensor ON, pos=0%%")
                return

        if self._open_sensor:
            state = self.hass.states.get(self._open_sensor)
            if state and state.state == STATE_ON:
                self._position = 100.0
                self._position_at_start = 100.0
                self._next_direction_is_open = False
                self._motor_state = MOTOR_STATE_IDLE
                _LOGGER.info("Startup calibration: open sensor ON, pos=100%%")
                return

        _LOGGER.debug("No sensor calibration on startup")

    def _reset_to_position(self, position: float, next_open: bool) -> None:
        """Hard-reset cover state from sensor feedback."""
        was_moving = self._motor_state != MOTOR_STATE_IDLE
        self._cancel_timer()
        self._position = position
        self._motor_state = MOTOR_STATE_IDLE
        self._target_position = None
        self._movement_started_at = None
        self._position_at_start = position
        self._next_direction_is_open = next_open
        _LOGGER.info(
            "Sensor reset: pos=%.0f%%, was_moving=%s, next=%s",
            position, was_moving, "open" if next_open else "close",
        )
        self.async_write_ha_state()

    @callback
    def _handle_closed_sensor(self, event: Event) -> None:
        """Handle closed sensor state change."""
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        if new_state.state == STATE_ON:
            _LOGGER.debug("Closed sensor ON")
            self._reset_to_position(0.0, next_open=True)

    @callback
    def _handle_open_sensor(self, event: Event) -> None:
        """Handle open sensor state change."""
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        if new_state.state == STATE_ON:
            _LOGGER.debug("Open sensor ON")
            self._reset_to_position(100.0, next_open=False)
