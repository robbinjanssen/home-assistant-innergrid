# pylint can't see the fields that the descriptions inherit from Home
# Assistant's entity descriptions.
# pylint: disable=unexpected-keyword-arg
"""Sensors for the Innergrid integration."""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    CURRENCY_EURO,
    DEGREE,
    LIGHT_LUX,
    PERCENTAGE,
    EntityCategory,
    UnitOfApparentPower,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfInformation,
    UnitOfPower,
    UnitOfRatio,
    UnitOfReactiveEnergy,
    UnitOfReactivePower,
    UnitOfTemperature,
)

from innergrid import (
    Categories,
    ChargePoint,
    ElectricityMeter,
    Kind,
    Quantity,
    Site,
    SiteMeter,
)

from .entity import (
    EntityTarget,
    InnergridEntity,
    InnergridEntityDescription,
    category_device,
    chargepoint_device,
    energy_manager_device,
    meter_device,
    milesight_device,
    setup_discovery,
    site_device,
    space_device,
    system_device,
    targets,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime, timedelta

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from innergrid import Circuit, Update

    from .entity import InnergridDevice
    from .hub import InnergridConfigEntry, InnergridHub

PRICE_UNIT = f"{CURRENCY_EURO}/{UnitOfEnergy.KILO_WATT_HOUR}"


@dataclass(frozen=True, kw_only=True)
class InnergridSensorEntityDescription(
    InnergridEntityDescription, SensorEntityDescription
):
    """Describes an Innergrid sensor."""


def _lower(value: str | None) -> str | None:
    """Return a status such as SUSPENDED_BY_EV as a state: suspended_by_ev."""
    return value.lower() if value else None


def _percentage(ratio: float | None) -> float | None:
    """Convert a load factor such as 0.25 to a percentage."""
    return None if ratio is None else round(ratio * 100, 1)


def _started_at(uptime: timedelta | None, received: datetime) -> datetime | None:
    """Return the start time from an uptime and when it was received.

    The start time is rounded to the minute, so it does not change with every
    message, unlike the uptime.
    """
    if uptime is None:
        return None
    return (received - uptime).replace(second=0, microsecond=0)


def _exists(value_fn: Callable[[Any], Any]) -> Callable[[Any], bool]:
    """Return a function that checks that the value is known."""
    return lambda data: value_fn(data) is not None


def _power(
    key: str, value_fn: Callable[[Any], Any], *, exists: bool = False, **kwargs: Any
) -> InnergridSensorEntityDescription:
    """Describe a power sensor in watt.

    With exists, the sensor is only created when the value is known.
    """
    if exists:
        kwargs["exists_fn"] = _exists(value_fn)
    return InnergridSensorEntityDescription(
        key=key,
        translation_key=kwargs.pop("translation_key", key),
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=value_fn,
        **kwargs,
    )


def _energy_24h(
    key: str, value_fn: Callable[[Any], Any], **kwargs: Any
) -> InnergridSensorEntityDescription:
    """Describe the energy of the last 24 hours in kWh.

    A moving total goes up and down, so it has no state class and no
    long-term statistics.
    """
    return InnergridSensorEntityDescription(
        key=key,
        translation_key=kwargs.pop("translation_key", key),
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=value_fn,
        exists_fn=_exists(value_fn),
        **kwargs,
    )


def _money_24h(
    key: str, value_fn: Callable[[Any], Any]
) -> InnergridSensorEntityDescription:
    """Describe an amount of the last 24 hours in euro."""
    return InnergridSensorEntityDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_EURO,
        suggested_display_precision=2,
        value_fn=value_fn,
        exists_fn=_exists(value_fn),
    )


def _price(
    key: str, value_fn: Callable[[Any], Any], **kwargs: Any
) -> InnergridSensorEntityDescription:
    """Describe an energy price in euro per kWh."""
    return InnergridSensorEntityDescription(
        key=key,
        translation_key=key,
        native_unit_of_measurement=PRICE_UNIT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        value_fn=value_fn,
        exists_fn=_exists(value_fn),
        **kwargs,
    )


def _timestamp(
    key: str, value_fn: Callable[[Any], Any], **kwargs: Any
) -> InnergridSensorEntityDescription:
    """Describe a timestamp sensor."""
    return InnergridSensorEntityDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=value_fn,
        **kwargs,
    )


def _status(
    key: str, value_fn: Callable[[Any], str | None], **kwargs: Any
) -> InnergridSensorEntityDescription:
    """Describe a status, shown in lower case with translated states."""
    return InnergridSensorEntityDescription(
        key=key,
        translation_key=key,
        value_fn=lambda data: _lower(value_fn(data)),
        **kwargs,
    )


def _site_meter(
    meter: str, value_fn: Callable[[SiteMeter], float | None]
) -> Callable[[Any], float | None]:
    """Return a function that gets a value of a meter of the site."""

    def value(site: Any) -> float | None:
        site_meter: SiteMeter | None = getattr(site, meter)
        return None if site_meter is None else value_fn(site_meter)

    return value


SITE_SENSORS: list[InnergridSensorEntityDescription] = [
    _power("grid_power", _site_meter("grid", lambda m: m.active_power), exists=True),
    _energy_24h(
        "grid_energy_imported_24h", _site_meter("grid", lambda m: m.energy_imported_24h)
    ),
    _energy_24h(
        "grid_energy_exported_24h", _site_meter("grid", lambda m: m.energy_exported_24h)
    ),
    _power(
        "grid_peak_import",
        _site_meter("grid", lambda m: m.max_power_quarter_hour_import),
        exists=True,
    ),
    _power(
        "grid_peak_export",
        _site_meter("grid", lambda m: m.max_power_quarter_hour_export),
        exists=True,
        entity_registry_enabled_default=False,
    ),
    _power(
        "grid_import_limit",
        _site_meter("grid", lambda m: m.continuous_import_limit),
        exists=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    _power(
        "grid_export_limit",
        _site_meter("grid", lambda m: m.continuous_export_limit),
        exists=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    _power(
        "production_power",
        _site_meter("production", lambda m: m.active_power),
        exists=True,
    ),
    _energy_24h(
        "production_energy_24h",
        _site_meter("production", lambda m: m.energy_exported_24h),
    ),
    _power(
        "production_peak",
        _site_meter("production", lambda m: m.max_power_quarter_hour_export),
        exists=True,
        entity_registry_enabled_default=False,
    ),
    _power(
        "consumption_power",
        _site_meter("consumption", lambda m: m.active_power),
        exists=True,
    ),
    _energy_24h(
        "consumption_energy_24h",
        _site_meter("consumption", lambda m: m.energy_imported_24h),
    ),
    _power(
        "consumption_peak",
        _site_meter("consumption", lambda m: m.max_power_quarter_hour_import),
        exists=True,
        entity_registry_enabled_default=False,
    ),
    _power(
        "battery_power",
        _site_meter("battery_storage", lambda m: m.active_power),
        exists=True,
    ),
    _money_24h("expense_24h", lambda site: site.expense_24h),
    _money_24h("revenue_24h", lambda site: site.revenue_24h),
    _price("energy_price_import", lambda site: site.energy_price_import),
    _price("energy_price_export", lambda site: site.energy_price_export),
    InnergridSensorEntityDescription(
        key="main_circuit_load",
        translation_key="main_circuit_load",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda site: _percentage(site.main_circuit_load_factor),
        exists_fn=lambda site: site.main_circuit_load_factor is not None,
    ),
]


@functools.cache
def _category_sensors(category: str) -> list[InnergridSensorEntityDescription]:
    """Describe the sensors of an energy category of a site."""

    def field(name: str) -> Callable[[Any], float | None]:
        def value(categories: Categories) -> float | None:
            if (values := categories.categories.get(category)) is None:
                return None
            result: float | None = getattr(values, name)
            return result

        return value

    return [
        _power("power", field("active_power"), exists=True),
        _energy_24h(
            "energy_imported_24h",
            field("energy_imported_24h"),
            translation_key="category_energy_imported_24h",
        ),
        _energy_24h(
            "energy_exported_24h",
            field("energy_exported_24h"),
            translation_key="category_energy_exported_24h",
        ),
        _money_24h("expense_24h", field("expense_24h")),
        _money_24h("revenue_24h", field("revenue_24h")),
    ]


@dataclass(frozen=True)
class QuantityType:
    """The device class, unit and state class of a meter's quantity."""

    device_class: SensorDeviceClass | None
    unit: str | None
    state_class: SensorStateClass | None = SensorStateClass.MEASUREMENT
    entity_category: EntityCategory | None = None


# How to show a meter's quantity, by the unit in the payload.
QUANTITY_TYPES: dict[str, QuantityType] = {
    "energy.kiloWattHour": QuantityType(
        SensorDeviceClass.ENERGY,
        UnitOfEnergy.KILO_WATT_HOUR,
        SensorStateClass.TOTAL_INCREASING,
    ),
    "power.watt": QuantityType(SensorDeviceClass.POWER, UnitOfPower.WATT),
    "current.ampere": QuantityType(
        SensorDeviceClass.CURRENT, UnitOfElectricCurrent.AMPERE
    ),
    "voltage.volt": QuantityType(
        SensorDeviceClass.VOLTAGE, UnitOfElectricPotential.VOLT
    ),
    "apparentPower.voltAmpere": QuantityType(
        SensorDeviceClass.APPARENT_POWER, UnitOfApparentPower.VOLT_AMPERE
    ),
    "reactivePower.voltAmpsReactive": QuantityType(
        SensorDeviceClass.REACTIVE_POWER, UnitOfReactivePower.VOLT_AMPERE_REACTIVE
    ),
    "powerFactor": QuantityType(SensorDeviceClass.POWER_FACTOR, None),
    "frequency.hertz": QuantityType(SensorDeviceClass.FREQUENCY, UnitOfFrequency.HERTZ),
    "reactiveEnergy.kiloVoltAmpereReactiveHour": QuantityType(
        SensorDeviceClass.REACTIVE_ENERGY,
        UnitOfReactiveEnergy.KILO_VOLT_AMPERE_REACTIVE_HOUR,
        SensorStateClass.TOTAL_INCREASING,
    ),
    "totalHarmonicDistortion.percentage": QuantityType(None, PERCENTAGE),
    "angle.degree": QuantityType(None, DEGREE),
    "currentTransformerPrimaryCurrentRange.ampere": QuantityType(
        SensorDeviceClass.CURRENT,
        UnitOfElectricCurrent.AMPERE,
        None,
        EntityCategory.DIAGNOSTIC,
    ),
    "bitmask.int": QuantityType(None, None, None, EntityCategory.DIAGNOSTIC),
    "ratio.float": QuantityType(None, None),
}

# Meter quantities with a translated name. Others use the name in the payload.
TRANSLATED_QUANTITIES = {
    "activePower",
    "apparentPower",
    "chargerVersusGridVoltageRatio",
    "contactorVoltage",
    "current",
    "currentNeutral",
    "currentTransformerPrimaryCurrentRange",
    "energyChargedInCurrentSession",
    "energyExported",
    "energyImported",
    "frequency",
    "maximumCurrent",
    "phaseAngle",
    "powerFactor",
    "reactiveEnergyExported",
    "reactiveEnergyImported",
    "reactivePower",
    "totalHarmonicCurrentDistortion",
    "totalHarmonicVoltageDistortion",
    "voltage",
    "warnings",
}
# The meter sensors that are enabled by default; the others can be enabled
# in Home Assistant when needed.
ENABLED_QUANTITIES = {"activePower", "energyImported", "energyExported"}
PHASE_PATTERN = re.compile(r"(.+?)(L[123])")


def _snake_case(name: str) -> str:
    """Convert a quantity such as activePower to active_power."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


@functools.cache
def _meter_sensor(key: str, quantity: Quantity) -> InnergridSensorEntityDescription:
    """Describe a sensor for a quantity of an electricity meter.

    Args:
    ----
        key: The quantity, for example activePower or activePowerL1.
        quantity: The name and unit of the quantity in the payload.

    """
    quantity_type = QUANTITY_TYPES.get(quantity.unit, QuantityType(None, None))
    base, phase = key, None
    if match := PHASE_PATTERN.fullmatch(key):
        base, phase = match.groups()
    naming: dict[str, Any] = {"name": quantity.name}
    if base in TRANSLATED_QUANTITIES:
        naming = {"translation_key": _snake_case(base)}
        if phase is not None:
            naming = {
                "translation_key": f"{_snake_case(base)}_phase",
                "translation_placeholders": {"phase": phase},
            }

    def value(meter: ElectricityMeter) -> float | None:
        return meter.measurements.get(key)

    return InnergridSensorEntityDescription(
        key=key,
        device_class=quantity_type.device_class,
        native_unit_of_measurement=quantity_type.unit,
        state_class=quantity_type.state_class,
        entity_category=quantity_type.entity_category,
        entity_registry_enabled_default=phase is None and base in ENABLED_QUANTITIES,
        value_fn=value,
        **naming,
    )


def _circuit_current(phase: str) -> InnergridSensorEntityDescription:
    """Describe the current of a phase of a circuit."""
    attribute = f"current_{phase.lower()}"
    return InnergridSensorEntityDescription(
        key=f"circuit_current_{phase.lower()}",
        translation_key="circuit_current",
        translation_placeholders={"phase": phase},
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda circuit: getattr(circuit, attribute),
        exists_fn=lambda circuit: getattr(circuit, attribute) is not None,
    )


def _circuit_load(minutes: int) -> InnergridSensorEntityDescription:
    """Describe the load factor of a circuit over a period."""
    attribute = f"load_factor_{minutes}m"
    return InnergridSensorEntityDescription(
        key=f"circuit_load_{minutes}m",
        translation_key="circuit_load",
        translation_placeholders={"minutes": str(minutes)},
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda circuit: _percentage(getattr(circuit, attribute)),
        exists_fn=lambda circuit: getattr(circuit, attribute) is not None,
    )


CIRCUIT_SENSORS: list[InnergridSensorEntityDescription] = [
    _circuit_current("L1"),
    _circuit_current("L2"),
    _circuit_current("L3"),
    _circuit_load(1),
    _circuit_load(5),
    _circuit_load(15),
    _power(
        "circuit_average_power_import",
        lambda circuit: circuit.average_power_import_15m,
        exists=True,
        entity_registry_enabled_default=False,
    ),
    _power(
        "circuit_average_power_export",
        lambda circuit: circuit.average_power_export_15m,
        exists=True,
        entity_registry_enabled_default=False,
    ),
    InnergridSensorEntityDescription(
        key="circuit_current_limit",
        translation_key="circuit_current_limit",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda circuit: circuit.current_limit,
        exists_fn=lambda circuit: circuit.current_limit is not None,
    ),
    InnergridSensorEntityDescription(
        key="circuit_warnings",
        translation_key="circuit_warnings",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda circuit: circuit.warnings,
        exists_fn=lambda circuit: circuit.warnings is not None,
    ),
]

CHARGEPOINT_SENSORS: list[InnergridSensorEntityDescription] = [
    _status("status", lambda charge_point: charge_point.status),
    _status("charging_state", lambda charge_point: charge_point.charging_state),
    _status("charge_strategy", lambda charge_point: charge_point.charge_strategy),
    _power("charging_power", lambda charge_point: charge_point.active_power),
    InnergridSensorEntityDescription(
        key="session_energy",
        translation_key="session_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value_fn=lambda charge_point: charge_point.energy_charged,
    ),
    InnergridSensorEntityDescription(
        key="target_energy",
        translation_key="target_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=lambda charge_point: charge_point.target_energy,
    ),
    _timestamp("departure", lambda charge_point: charge_point.departure_at),
    _timestamp("session_start", lambda charge_point: charge_point.started_at),
    _timestamp("session_end", lambda charge_point: charge_point.session_finished_at),
    InnergridSensorEntityDescription(
        key="user",
        translation_key="user",
        value_fn=lambda charge_point: charge_point.current_user,
    ),
    InnergridSensorEntityDescription(
        key="charge_current",
        translation_key="charge_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda charge_point: charge_point.charge_current,
    ),
    InnergridSensorEntityDescription(
        key="phases_enabled",
        translation_key="phases_enabled",
        entity_registry_enabled_default=False,
        value_fn=lambda charge_point: charge_point.phases_enabled,
    ),
    _power(
        "power_instruction",
        lambda charge_point: charge_point.power_instruction,
        entity_registry_enabled_default=False,
    ),
    _power(
        "minimum_power",
        lambda charge_point: charge_point.minimum_power,
        entity_registry_enabled_default=False,
    ),
]


def _manager_power(key: str, **kwargs: Any) -> InnergridSensorEntityDescription:
    """Describe a power value of the energy manager, named like its attribute."""
    return _power(
        key,
        lambda manager: getattr(manager, key),
        exists=True,
        translation_key=f"manager_{key}",
        **kwargs,
    )


def _manager_limit(key: str) -> InnergridSensorEntityDescription:
    """Describe a power limit of the energy manager."""
    return _manager_power(
        key,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    )


ENERGY_MANAGER_SENSORS: list[InnergridSensorEntityDescription] = [
    _manager_power("grid_power"),
    _manager_power("solar_power"),
    _manager_power("charge_point_power"),
    _manager_power("climate_power"),
    _manager_power("baseload_power"),
    _manager_power("inflexible_power"),
    _manager_power("battery_power", entity_registry_enabled_default=False),
    _manager_power("optimized_import_power", entity_registry_enabled_default=False),
    _manager_power("flexible_power", entity_registry_enabled_default=False),
    _manager_limit("continuous_import_limit"),
    _manager_limit("instantaneous_import_limit"),
    _manager_limit("continuous_export_limit"),
    _manager_limit("instantaneous_export_limit"),
    _manager_limit("peak_shaving_limit"),
    _status("optimization_goal", lambda manager: manager.optimization_goal),
    _status(
        "binding_limit",
        lambda manager: manager.binding_limit,
        entity_registry_enabled_default=False,
    ),
    InnergridSensorEntityDescription(
        key="strategy",
        translation_key="strategy",
        entity_registry_enabled_default=False,
        # A state is limited to 255 characters.
        value_fn=lambda manager: manager.strategy[:255] if manager.strategy else None,
    ),
    _timestamp("cheapest_period_start", lambda manager: manager.cheapest_period_start),
    _price("cheapest_period_price", lambda manager: manager.cheapest_period_price),
    _price(
        "baseline_price",
        lambda manager: manager.baseline_price,
        entity_registry_enabled_default=False,
    ),
]


def _measured(name: str) -> Callable[[Any], bool]:
    """Return a function that checks that a space or sensor measures a value.

    Values that are not plausible are None, so the entity is created based
    on what the sensor measures; it shows unknown until the value is valid.
    """
    return lambda data: name in data.measured


CLIMATE_SENSORS: list[InnergridSensorEntityDescription] = [
    InnergridSensorEntityDescription(
        key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.temperature,
        exists_fn=_measured("temperature"),
    ),
    InnergridSensorEntityDescription(
        key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.humidity,
        exists_fn=_measured("humidity"),
    ),
    InnergridSensorEntityDescription(
        key="co2",
        device_class=SensorDeviceClass.CO2,
        native_unit_of_measurement=UnitOfRatio.PARTS_PER_MILLION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.co2,
        exists_fn=_measured("co2"),
    ),
]

ILLUMINANCE_SENSOR = InnergridSensorEntityDescription(
    key="illuminance",
    device_class=SensorDeviceClass.ILLUMINANCE,
    native_unit_of_measurement=LIGHT_LUX,
    state_class=SensorStateClass.MEASUREMENT,
    value_fn=lambda data: data.illuminance,
    exists_fn=_measured("illuminance"),
)

SPACE_SENSORS: list[InnergridSensorEntityDescription] = [
    *CLIMATE_SENSORS,
    ILLUMINANCE_SENSOR,
    InnergridSensorEntityDescription(
        key="air_quality",
        translation_key="air_quality",
        value_fn=lambda space: _lower(space.air_quality),
        exists_fn=_measured("air_quality"),
    ),
    InnergridSensorEntityDescription(
        key="low_battery_count",
        translation_key="low_battery_count",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda space: space.low_battery_count,
        exists_fn=lambda space: space.low_battery_count is not None,
    ),
]

MILESIGHT_SENSORS: list[InnergridSensorEntityDescription] = [
    *CLIMATE_SENSORS,
    ILLUMINANCE_SENSOR,
    InnergridSensorEntityDescription(
        key="battery_voltage",
        translation_key="battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
        suggested_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda sensor: sensor.battery_voltage,
        exists_fn=_measured("battery_voltage"),
    ),
]


def _system(
    key: str, value_fn: Callable[[Any], Any], **kwargs: Any
) -> InnergridSensorEntityDescription:
    """Describe a diagnostic sensor of the server."""
    return InnergridSensorEntityDescription(
        key=key,
        translation_key=key,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=value_fn,
        exists_fn=_exists(value_fn),
        **kwargs,
    )


def _system_data_size(
    key: str, value_fn: Callable[[Any], Any], **kwargs: Any
) -> InnergridSensorEntityDescription:
    """Describe a memory or disk size in MiB of the server."""
    return _system(
        key,
        value_fn,
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.MEBIBYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIBIBYTES,
        state_class=SensorStateClass.MEASUREMENT,
        **kwargs,
    )


SYSTEM_SENSORS: list[InnergridSensorEntityDescription] = [
    _system(
        "cpu_usage",
        lambda system: system.cpu_usage,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    _system_data_size("memory_available", lambda system: system.memory_available),
    _system_data_size(
        "memory_total",
        lambda system: system.memory_total,
        entity_registry_enabled_default=False,
    ),
    _system_data_size("disk_free", lambda system: system.disk_free),
    _system_data_size(
        "disk_total",
        lambda system: system.disk_total,
        entity_registry_enabled_default=False,
    ),
    _system(
        "last_backup",
        lambda system: system.last_backup_at,
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    _system(
        "system_started",
        lambda system: system.system_uptime,
        device_class=SensorDeviceClass.TIMESTAMP,
        time_fn=lambda system, received: _started_at(system.system_uptime, received),
    ),
    _system(
        "symcon_started",
        lambda system: system.symcon_uptime,
        device_class=SensorDeviceClass.TIMESTAMP,
        time_fn=lambda system, received: _started_at(system.symcon_uptime, received),
    ),
    _system(
        "module_library_version",
        lambda system: system.module_library_version,
        entity_registry_enabled_default=False,
    ),
    _system(
        "io_connection_faults",
        lambda system: system.io_connection_faults,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    _system(
        "instances_not_active",
        lambda system: system.instances_not_active,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    _system(
        "overdue_timers",
        lambda system: system.overdue_timers,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    _system(
        "backup_file_count",
        lambda system: system.backup_file_count,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    _system(
        "api_request_count",
        lambda system: system.api_request_count,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
    ),
]


def _category_targets(_hub: InnergridHub, update: Update) -> list[EntityTarget]:
    """Return the sensors of each energy category of a site."""
    data: Categories = _model(update)
    result: list[EntityTarget] = []
    for key, category in data.categories.items():
        result += targets(
            update.key,
            functools.partial(category_device, update.id, key, category.name),
            _category_sensors(key),
            data,
        )
    return result


# The totals of the site's meters, shown on the site's device for the energy
# dashboard: by role, the sensor key and the meter's quantity.
SITE_METER_TOTALS: dict[str, list[tuple[str, str]]] = {
    "grid": [
        ("grid_energy_imported_total", "energyImported"),
        ("grid_energy_exported_total", "energyExported"),
    ],
    "production": [("production_energy_total", "energyExported")],
    "consumption": [("consumption_energy_total", "energyImported")],
}
SITE_METER_QUANTITIES = {"energyImported", "energyExported"}


@functools.cache
def _site_meter_sensors(role: str) -> list[InnergridSensorEntityDescription]:
    """Describe the totals of a meter of the site."""

    def total(quantity: str) -> Callable[[Any], float | None]:
        return lambda meter: meter.measurements.get(quantity)

    def measured(quantity: str) -> Callable[[Any], bool]:
        return lambda meter: quantity in meter.quantities

    return [
        InnergridSensorEntityDescription(
            key=key,
            translation_key=key,
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            state_class=SensorStateClass.TOTAL_INCREASING,
            value_fn=total(quantity),
            exists_fn=measured(quantity),
        )
        for key, quantity in SITE_METER_TOTALS.get(role, [])
    ]


def _site_role(hub: InnergridHub, meter: ElectricityMeter) -> tuple[str, str]:
    """Return the ID of the site and the role of a meter of the site.

    The role is grid, production or consumption, or empty for other meters.
    """
    for update in hub.of_kind(Kind.SITE):
        site: Site = _model(update)
        for role in SITE_METER_TOTALS:
            site_meter: SiteMeter | None = getattr(site, role)
            if site_meter is not None and site_meter.id == meter.id:
                return update.id, role
    return "", ""


def _meter_device(hub: InnergridHub, meter: ElectricityMeter) -> InnergridDevice | None:
    """Return the device of a meter, or None while it is not known yet.

    The meter of a charger (Zaptec) belongs to the device of the charge point
    with the same name; the data has no other link between them.
    """
    if meter.manufacturer != "Zaptec":
        return meter_device(meter)
    for update in hub.of_kind(Kind.CHARGE_POINT):
        charge_point: ChargePoint = _model(update)
        if charge_point.name == meter.name:
            return replace(
                chargepoint_device(charge_point),
                manufacturer=meter.manufacturer,
                model=meter.module_name,
            )
    return None


def _meter_targets(hub: InnergridHub, update: Update) -> list[EntityTarget]:
    """Return the sensors of the quantities that a meter measures.

    They are added once the site is known, as it tells which meters are the
    site's grid connection, production and consumption; the totals of those
    are on the site's device.
    """
    meter: ElectricityMeter = _model(update)
    if not hub.of_kind(Kind.SITE):
        return []
    if (device := _meter_device(hub, meter)) is None:
        return []
    site_id, role = _site_role(hub, meter)
    descriptions = [
        _meter_sensor(key, quantity)
        for key, quantity in meter.quantities.items()
        if not role or key not in SITE_METER_QUANTITIES
    ]
    result = targets(update.key, lambda: device, descriptions, meter)
    if role:
        result += targets(
            update.key, lambda: site_device(site_id), _site_meter_sensors(role), meter
        )
    return result


def _circuit_targets(hub: InnergridHub, update: Update) -> list[EntityTarget]:
    """Return the sensors of a circuit, on the device of the circuit's meter.

    They are added once the meter is known, as its data names the device.
    """
    circuit: Circuit = _model(update)
    meter = hub.data.get(f"{Kind.METER}/{circuit.electricity_meter_id}")
    if meter is None or not isinstance(meter.data, ElectricityMeter):
        return []
    if (device := _meter_device(hub, meter.data)) is None:
        return []
    return targets(update.key, lambda: device, CIRCUIT_SENSORS, circuit)


def _simple_targets(
    device_fn: Callable[[InnergridHub, Update], Any],
    descriptions: list[InnergridSensorEntityDescription],
) -> Callable[[InnergridHub, Update], list[EntityTarget]]:
    """Return a function that returns the targets of a topic with one device."""
    return lambda hub, update: targets(
        update.key, lambda: device_fn(hub, update), descriptions, update.data
    )


def _model(update: Update) -> Any:
    """Return the model of an update; its type follows from the kind."""
    return update.data


TARGETS_BY_KIND: dict[Kind, Callable[[InnergridHub, Update], list[EntityTarget]]] = {
    Kind.SITE: _simple_targets(
        lambda _hub, update: site_device(update.id), SITE_SENSORS
    ),
    Kind.CATEGORIES: _category_targets,
    Kind.METER: _meter_targets,
    Kind.CIRCUIT: _circuit_targets,
    Kind.CHARGE_POINT: _simple_targets(
        lambda _hub, update: chargepoint_device(_model(update)),
        CHARGEPOINT_SENSORS,
    ),
    Kind.ENERGY_MANAGER: _simple_targets(
        lambda _hub, update: energy_manager_device(_model(update)),
        ENERGY_MANAGER_SENSORS,
    ),
    Kind.SPACE: _simple_targets(
        lambda hub, update: space_device(update.id, hub.space_names.get(update.id)),
        SPACE_SENSORS,
    ),
    Kind.SYSTEM: _simple_targets(
        lambda _hub, update: system_device(_model(update)),
        SYSTEM_SENSORS,
    ),
    Kind.MILESIGHT: _simple_targets(
        lambda _hub, update: milesight_device(update.id), MILESIGHT_SENSORS
    ),
}


def sensor_targets(hub: InnergridHub, key: str) -> list[EntityTarget]:
    """Return the sensors that the data of a key can have."""
    update = hub.data[key]
    if (targets_fn := TARGETS_BY_KIND.get(update.kind)) is None:
        return []
    return targets_fn(hub, update)


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: InnergridConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add sensors for the data as it arrives.

    Args:
    ----
        _hass: The HomeAssistant instance.
        entry: The ConfigEntry containing the user input.
        async_add_entities: The callback to provide the created entities to.

    """
    hub = entry.runtime_data
    entry.async_on_unload(
        setup_discovery(
            hub,
            sensor_targets,
            lambda target: InnergridSensor(hub, target),
            async_add_entities,
        )
    )


class InnergridSensor(InnergridEntity, SensorEntity):
    """A sensor with a value from the data of one topic."""

    entity_description: InnergridSensorEntityDescription

    @property
    def native_value(self) -> Any:
        """Return the value of the sensor."""
        return self.data_value
