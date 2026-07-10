# Virtual Garage Cover

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

A Home Assistant integration for garage doors and covers controlled by a **single-button motor** -- one button that cycles through **Open > Stop > Close > Stop**.

## The Problem

Many garage door openers, gate motors, and rolling shutters use a simple single-button control: one press cycles the motor direction. There's no native position feedback -- just a toggle switch.

Home Assistant's built-in cover template requires manual scripting with helpers, timers, and automations to track position and handle direction reversal. This integration packages all of that into a clean, configurable component.

## Features

- **Position tracking** -- Estimates position (0-100%) based on travel time
- **Partial positioning** -- Set any position via `set_cover_position` (e.g., open to 25%)
- **Single-button direction handling** -- Automatically manages the Open>Stop>Close>Stop cycle, including triple-press for direction reversal
- **Endstop sensor calibration** -- Optional binary sensors for closed/open detection auto-calibrate position
- **Smart sensor polarity** -- Automatically detects sensor device_class (garage_door, door, etc.) and handles ON/OFF polarity correctly
- **State invariant protection** -- Cover state always matches sensor feedback; impossible states are auto-corrected
- **State restoration** -- Position and direction survive HA restarts
- **Configurable toggle delay** -- Adjust timing between rapid presses for your motor

## Prerequisites

### Minimum Required

| Component | Example | Purpose |
|-----------|---------|---------|
| **Smart relay/switch** | Shelly 1, Sonoff Basic, Shelly Plus 1 | Controls the motor -- appears as `switch.*` in HA |
| **Door/gate contact sensor** | Aqara Door Sensor, Shelly Door/Window | Detects fully closed position -- appears as `binary_sensor.*` in HA |

The switch must be wired to the garage motor's button input (the same terminal your wall button connects to). Each `switch.turn_on` call simulates a button press.

### Recommended (for better accuracy)

| Component | Example | Purpose |
|-----------|---------|---------|
| **Open-position sensor** | Reed switch at top of travel | Detects fully open position -- eliminates drift over time |

### Wiring Diagram

```
                    +---------------+
Wall Button --------+               |
                    |  Garage       +---- Motor
Smart Relay --------+  Motor        |
(Shelly 1)  --------+  Controller   |
                    +---------------+

Door Sensor (magnetic) ---- mounted at closed position
Open Sensor (optional) ---- mounted at open position
```

> **Tip:** Measure the full travel time (fully open > fully closed) with a stopwatch. Precision here directly affects position accuracy.

## Architecture

![Architecture](docs/architecture.svg)

## Installation

### HACS (recommended)

1. Open HACS > Integrations > **Custom Repositories**
2. Add `https://github.com/Grrzzz/ha-virtual-garage-cover` as an Integration
3. Install **Virtual Garage Cover**
4. Restart Home Assistant

### Manual

1. Copy `custom_components/virtual_garage_cover/` to your `config/custom_components/` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings > Devices & Services > Add Integration**
2. Search for **Virtual Garage Cover**
3. Configure:

| Parameter | Required | Description |
|-----------|----------|-------------|
| Toggle switch | Yes | The `switch.*` entity that controls the motor |
| Full travel time | Yes | Time (seconds) for full open<>closed travel (default: 20s) |
| Closed sensor | No | `binary_sensor.*` for closed detection (polarity auto-detected) |
| Open sensor | No | `binary_sensor.*` for open detection (polarity auto-detected) |
| Toggle delay | No | Delay between rapid presses in seconds (default: 0.25s) |

### Sensor Polarity

The integration automatically detects the sensor's `device_class` and handles polarity:

- **garage_door, door, opening, window, gate**: HA convention (ON=open, OFF=closed)
- **Other / no device_class**: ON = endstop reached

You do not need to configure polarity manually.

## How It Works

### Single-Button Motor Logic

The motor follows this cycle on each button press:

```
Press 1: Motor starts (direction depends on last movement)
Press 2: Motor stops
Press 3: Motor starts (opposite direction)
Press 4: Motor stops
... and so on
```

### Direction Reversal

When the cover needs to move in the opposite direction from what the next press would do, the integration performs a **triple-press**:
1. Press 1 > Motor starts (wrong direction)
2. Press 2 > Motor stops
3. Press 3 > Motor starts (correct direction)

The delay between presses is configurable (`toggle_delay`) to accommodate different motor response times.

### Position Estimation

Position is calculated based on elapsed time relative to the configured travel time. When endstop sensors are configured, they automatically calibrate the position to 0% or 100% when triggered, correcting any drift.

### State Protection

The integration enforces a strict invariant: the cover state must always be consistent with sensor feedback. If the closed sensor indicates the door is not closed but the position is 0%, the position is automatically corrected. This prevents impossible states even after physical manipulation of the door.

## Options

After setup, you can adjust travel time, sensors, and toggle delay via **Settings > Devices & Services > Virtual Garage Cover > Configure**.

## Supported Scenarios

- Garage doors with a single toggle relay (e.g., Shelly, Sonoff)
- Rolling shutters with single-button motors
- Gate openers with single-button control
- Any cover with Open>Stop>Close>Stop cycle

## License

MIT
