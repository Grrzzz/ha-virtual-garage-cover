# Home Assistant Virtual Garage Cover

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

*A virtual garage door for Home Assistant.*

Create a garage door entity without requiring a physical garage door controller.

---

## Why?

Many garage door setups do not expose a native Home Assistant `cover` entity.
Examples include:

- Custom ESPHome or MQTT solutions
- Relay-based openers
- REST API integrations
- Proprietary gateways
- Cloud-connected garage systems
- Testing environments and demos

This integration provides a standard garage door entity that behaves like a normal Home Assistant cover and can be controlled through automations and dashboards.

## Features

- Native Home Assistant garage door entity
- Open / Close / Stop / Set Position support
- Position tracking based on travel time
- Automatic sensor calibration (closed and open endstop sensors)
- Smart sensor polarity detection (respects `device_class`)
- State protection -- cover state always matches sensor feedback
- Direction management with automatic triple-press reversal
- State restoration across restarts
- Dashboard-friendly
- Works with automations, scripts and scenes
- Simple setup through UI
- Configurable toggle delay for different motor types

## Typical Use Cases

### Custom Relay Control

Use a relay (Shelly, Sonoff, ESPHome) to trigger a garage opener while exposing a proper garage door entity to Home Assistant.

### MQTT-Based Garage Doors

Create a garage cover that is connected to custom MQTT automations.

### REST API Integration

Bridge external garage door APIs into Home Assistant without writing a custom cover platform.

### Dashboard Control

Expose a clean garage door card in Lovelace even if the backend system does not provide a cover entity.

### Development & Testing

Simulate garage doors when developing automations or custom integrations.

## How It Works

```
Home Assistant: Automation / Script / Dashboard
 |
 v
Virtual Garage Cover
 |
 v
Switch Entity (with optional binary sensors)
 |
 v
Garage Door
```

The integration controls your garage motor through a `switch` entity. Each `switch.turn_on` simulates a button press. The motor follows a single-button cycle:

```
Press 1: Motor starts (direction depends on last movement)
Press 2: Motor stops
Press 3: Motor starts (opposite direction)
Press 4: Motor stops
```

When the cover needs to move in the opposite direction, the integration performs a **triple-press** (start wrong direction, stop, start correct direction). The delay between presses is configurable.

Position is estimated from travel time. Optional endstop sensors auto-calibrate to 0% or 100%, correcting any drift over time.

## Prerequisites

| Component | Example | Purpose |
|-----------|---------|---------|
| **Smart relay/switch** | Shelly 1, Sonoff Basic, ESPHome GPIO | Controls the motor -- appears as `switch.*` in HA |
| **Closed sensor** (recommended) | Aqara Door Sensor, reed switch | Detects fully closed position -- appears as `binary_sensor.*` |
| **Open sensor** (optional) | Reed switch at top of travel | Detects fully open position -- eliminates drift |

> **Tip:** Measure the full travel time (fully open to fully closed) with a stopwatch. Precision directly affects position accuracy.

## Installation

### HACS (recommended)

1. Open HACS > Integrations > Custom Repositories
2. Add `https://github.com/Grrzzz/ha-virtual-garage-cover` as an Integration
3. Install **Virtual Garage Cover**
4. Restart Home Assistant

### Manual

Copy `custom_components/virtual_garage_cover/` into your `config/custom_components/` directory. Restart Home Assistant.

## Configuration

Configuration is performed entirely through the Home Assistant UI.

1. Navigate to **Settings > Devices & Services > Add Integration**
2. Search for **Virtual Garage Cover**
3. Configure:

| Parameter | Required | Description |
|-----------|----------|-------------|
| Toggle switch | Yes | The `switch.*` entity that controls the motor |
| Full travel time | Yes | Seconds for full open-to-closed travel (default: 20s) |
| Closed sensor | No | `binary_sensor.*` for closed detection (polarity auto-detected) |
| Open sensor | No | `binary_sensor.*` for open detection (polarity auto-detected) |
| Toggle delay | No | Delay between rapid presses in seconds (default: 0.25s) |

After setup, adjust settings via **Settings > Devices & Services > Virtual Garage Cover > Configure**.

### Sensor Polarity

The integration automatically detects the sensor's `device_class` and handles polarity correctly:

- **garage_door, door, opening, window, gate**: HA convention (ON = open, OFF = closed)
- **Other / no device_class**: ON = endstop reached

No manual polarity configuration needed.

## Who Is This For?

This integration is for Home Assistant users who:

- want a proper garage door entity
- have custom automation logic
- use MQTT, REST or relay-based solutions
- need a virtual or simulated garage door
- want cleaner dashboards
- want position tracking without native controller support

## License

MIT
