# Innergrid Integration for Home Assistant

Reads the energy and building data of a customer site from the MQTT broker of the Innergrid energy management platform: the grid connection, energy categories, every
electricity meter and circuit, the charge points, the energy manager, the
spaces, the server and the Milesight LoRaWAN sensors.

The MQTT communication and the parsing of the messages live in the
[`innergrid`](https://github.com/robbinjanssen/python-innergrid)
library.

This integration requires Home Assistant 2026.10 or newer.

## Installation

### HACS

Add this repository as a custom repository in HACS (category
`Integration`), then install `Innergrid`.

### Manual

Copy `custom_components/innergrid/` from this repository into the
`<config directory>/custom_components/` directory of your Home Assistant
instance and restart Home Assistant.

## Configuration

Add the integration on the integrations page and enter:

| Field | Description |
| --- | --- |
| Host | The MQTT broker, for example `192.0.2.10`. |
| Port | The port of the broker, for example `1883`. |
| Username, password | Only if the broker requires a login. |
| Customer site slug | The slug of the customer site: the first part of its topics, for example `mysite`. |
| REST API URL, e-mail address, password | Optional: the REST API of the edge server, for example `http://192.0.2.10:31679/hook/api`, and a user of the edge server (Loqio WebApp). |

The integration connects to the broker itself, next to Home Assistant's own
MQTT integration, and checks the settings by waiting up to 30 seconds for a
message of the customer site. To change the settings later, choose
**Reconfigure** in the integration's menu.

With the REST API, the spaces get their names from the edge server, and the
chargers can be controlled (see below). Without it, everything else works the
same.

## Devices and entities

The platform's topics are retained, so all devices and entities are added
right after connecting; the Milesight sensors are not retained and publish
every 3 minutes. The integration also stores the latest data, so the entities
show their last values while the broker cannot be reached. Data that is not
updated for 15 minutes, or while the connection is lost, is unavailable.

When the platform removes a charger, meter, space or other instance, it
publishes an empty message on its topic; the integration then removes its
entities, and devices that have no entities left. An instance that was removed
while Home Assistant was not connected is removed when it has not arrived
again 2 minutes after connecting.

| Device | Entities |
| --- | --- |
| Site | Grid, production and consumption power, energy of the last 24 hours and totals, quarter-hour peaks, costs and revenue of the last 24 hours, energy prices |
| A device per category (Keuken, Verlichting, ...) | Power, energy, costs and revenue of the last 24 hours |
| A device per electricity meter (group) | Power, energy imported and exported. Disabled: current, voltage, power factor, harmonic distortion, per-phase values and the circuit's current and load |
| A device per charger (Lader 01, ...) | Status, charging power, session energy, session start and end, departure, user, charge current; plugged in and charging; the charger's meter (energy imported) and circuit; a "Charging session" event |
| Energy manager | Power of grid, solar, charge points, climate and base load; optimisation goal; cheapest period; abnormal condition |
| A device per space (`Ruimte <id>`) | Temperature, humidity, CO₂, illuminance, air quality; presence and occupancy once measured |
| Symcon server | CPU, memory, disk, last backup, start times, faults |
| A device per Milesight sensor | Temperature, humidity, CO₂, illuminance, battery voltage; motion (depending on the model) |

Disabled entities can be enabled on the device page.

Notes:

- A charger's meter (Zaptec) is linked to the charge point with the same name;
  the data has no other link. If a charger is renamed in the energy platform,
  its meter is added once a charge point with the new name exists.
- Meters are added once the site is known, as the site tells which meters are
  the grid connection, production and consumption.
- Spaces have no name in the data; rename the devices in Home Assistant.
- Values that are not plausible, such as -1001.1 °C or 0% humidity, are shown
  as unknown. Some sensors report those instead of an error.
- Production power is negative, as the meters measure it.
- The user of a charge point is only shown while a vehicle is connected.
  Diagnostics redact the names of people.

## Controlling the chargers

With the REST API configured, every charger has these controls, which change
its charging session on the edge server:

| Entity | Changes |
| --- | --- |
| Charge strategy (select) | Smart charging, direct charging or solar charging |
| Charging target (number) | The energy to charge in the session, in kWh |
| Departure (date and time) | The planned departure time |
| User (text) | The user of the session |
| Claimed (switch) | Whether a user claimed the session |

The new value is shown right away, and confirmed when the platform publishes
the charger again. Everyone who can use these entities in Home Assistant can
change the charging session of anyone's car; put them on a dashboard for the
people who should.

## Charging session events

The "Charging session" event of a charger fires as soon as its session
changes, for example when a vehicle starts or stops charging. Its attributes
hold the session after the change: `status`, `charging_state`, `plugged_in`,
`charging` and `user`. Use it in automations with a state trigger on the
event entity, and a condition on its attributes.

## Energy dashboard

Use the totals of the site device:

| Energy dashboard | Sensor |
| --- | --- |
| Grid consumption | Site: Grid energy imported |
| Return to grid | Site: Grid energy exported |
| Solar production | Site: Production energy |
| Individual devices | Energy imported of a charger or of a meter (group) |

The energy of the last 24 hours is a moving total without long-term
statistics, so it cannot be used in the energy dashboard.

## Development

The project uses [uv](https://docs.astral.sh/uv/) and
[prek](https://github.com/j178/prek).

```sh
uv sync
uv run prek install
uv run pytest
```
