# Tri-State Cover

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

A Home Assistant integration for garage doors and covers controlled by a **tri-state motor** — a single button that cycles through **Open → Stop → Close → Stop**.

## The Problem

Many garage door openers, gate motors, and rolling shutters use a simple tri-state control: one button press cycles the motor direction. There's no native position feedback — just a toggle switch.

Home Assistant's built-in cover template requires manual scripting with helpers, timers, and automations to track position and handle direction reversal. This integration packages all of that into a clean, configurable component.

## Features

- **Position tracking** — Estimates position (0–100%) based on travel time
- **Partial positioning** — Set any position via `set_cover_position` (e.g., open to 25%)
- **Tri-state direction handling** — Automatically manages the Open→Stop→Close→Stop cycle, including triple-press for direction reversal
- **Endstop sensor calibration** — Optional binary sensors for closed/open detection auto-calibrate position
- **State restoration** — Position and direction survive HA restarts
- **Configurable toggle delay** — Adjust timing between rapid presses for your motor

## Installation

### HACS (recommended)

1. Open HACS → Integrations → **Custom Repositories**
2. Add `https://github.com/Grrzzz/ha-tri-state-cover` as an Integration
3. Install **Tri-State Cover**
4. Restart Home Assistant

### Manual

1. Copy `custom_components/tri_state_cover/` to your `config/custom_components/` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Tri-State Cover**
3. Configure:

| Parameter | Required | Description |
|-----------|----------|-------------|
| Toggle switch | Yes | The `switch.*` entity that controls the motor |
| Full travel time | Yes | Time (seconds) for full open↔closed travel (default: 20s) |
| Closed sensor | No | `binary_sensor.*` that is ON when fully closed |
| Open sensor | No | `binary_sensor.*` that is ON when fully open |
| Toggle delay | No | Delay between rapid presses in seconds (default: 0.25s) |

## How It Works

### Tri-State Motor Logic

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
1. Press 1 → Motor starts (wrong direction)
2. Press 2 → Motor stops
3. Press 3 → Motor starts (correct direction)

The delay between presses is configurable (`toggle_delay`) to accommodate different motor response times.

### Position Estimation

Position is calculated based on elapsed time relative to the configured travel time. When endstop sensors are configured, they automatically calibrate the position to 0% or 100% when triggered, correcting any drift.

## Options

After setup, you can adjust travel time, sensors, and toggle delay via **Settings → Devices & Services → Tri-State Cover → Configure**.

## Supported Scenarios

- Garage doors with a single toggle relay (e.g., Shelly, Sonoff)
- Rolling shutters with tri-state motors
- Gate openers with single-button control
- Any cover with Open→Stop→Close→Stop cycle

## License

MIT
