"""Tests for the Innergrid sensors."""

import json
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from homeassistant.const import STATE_UNKNOWN
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from . import load_fixture
from .conftest import (
    DOMAIN,
    device,
    entity_id,
    send,
    send_all,
    send_site,
    state,
)

if TYPE_CHECKING:
    from freezegun.api import FrozenDateTimeFactory
    from homeassistant.core import HomeAssistant

STRINGS = json.loads(
    (
        Path(__file__).parent.parent
        / "custom_components"
        / "innergrid"
        / "strings.json"
    ).read_text()
)

pytestmark = pytest.mark.usefixtures("setup_integration")


async def test_site(hass: HomeAssistant) -> None:
    """Test the sensors of the site."""
    await send(hass, "mysite/customersites/34901/live", "site.json")
    assert state(hass, "sensor", "mysite_site_34901_grid_power") == "10802"
    assert state(hass, "sensor", "mysite_site_34901_production_power") == "-3200"
    assert state(hass, "sensor", "mysite_site_34901_expense_24h") == "92.35"
    assert state(hass, "sensor", "mysite_site_34901_energy_price_import") == "0.3"
    registry = er.async_get(hass)
    # The site has no battery.
    assert not registry.async_get_entity_id(
        "sensor", DOMAIN, "mysite_site_34901_battery_power"
    )
    limit = registry.async_get(
        entity_id(hass, "sensor", "mysite_site_34901_grid_import_limit")
    )
    assert limit is not None
    assert limit.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_categories(hass: HomeAssistant) -> None:
    """Test that each category is a device with its own sensors."""
    await send(hass, "mysite/categories/34901/live", "categories.json")
    assert state(hass, "sensor", "mysite_category_34901_kitchen_power") == "311"
    assert (
        state(hass, "sensor", "mysite_category_34901_kitchen_energy_imported_24h")
        == "7.79"
    )
    found = device(hass, (DOMAIN, "mysite_category_34901_kitchen"))
    assert found is not None
    assert found.name == "Keuken"


async def test_meter(hass: HomeAssistant) -> None:
    """Test that power and energy are enabled and other quantities disabled."""
    await send_site(hass)
    await send(hass, "mysite/electricitymeters/10005", "meter_single_phase.json")
    assert state(hass, "sensor", "mysite_meter_10005_activePower") == "-22"
    assert state(hass, "sensor", "mysite_meter_10005_energyImported") == "8.073"
    registry = er.async_get(hass)
    voltage = registry.async_get(
        entity_id(hass, "sensor", "mysite_meter_10005_voltage")
    )
    assert voltage is not None
    assert voltage.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    found = device(hass, (DOMAIN, "mysite_meter_10005"))
    assert found is not None
    assert found.name == "Groep 14"
    assert found.manufacturer == "Eastron"
    assert found.model == "Eastron SDM630MCTML 1P"


async def test_meter_phases(hass: HomeAssistant) -> None:
    """Test that the quantities of each phase are disabled."""
    await send_site(hass)
    await send(hass, "mysite/electricitymeters/37373", "meter_three_phase.json")
    entry = er.async_get(hass).async_get(
        entity_id(hass, "sensor", "mysite_meter_37373_activePowerL1")
    )
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert entry.translation_key == "active_power_phase"


async def test_circuit_on_meter_device(hass: HomeAssistant) -> None:
    """Test that circuit sensors are added to the meter's device once known."""
    registry = er.async_get(hass)
    await send(hass, "mysite/circuits/19923/live", "circuit.json")
    assert not registry.async_get_entity_id(
        "sensor", DOMAIN, "mysite_meter_37373_circuit_current_l1"
    )
    await send_site(hass)
    await send(hass, "mysite/electricitymeters/37373", "meter_three_phase.json")
    await send(hass, "mysite/circuits/19923/live", "circuit.json")
    entry = registry.async_get(
        entity_id(hass, "sensor", "mysite_meter_37373_circuit_current_l1")
    )
    assert entry is not None
    found = device(hass, (DOMAIN, "mysite_meter_37373"))
    assert found is not None
    assert entry.device_id == found.id


async def test_meter_waits_for_site(hass: HomeAssistant) -> None:
    """Test that meters are added once the site is known."""
    await send(hass, "mysite/electricitymeters/10005", "meter_single_phase.json")
    assert not er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, "mysite_meter_10005_activePower"
    )
    await send_site(hass)
    await send(hass, "mysite/electricitymeters/10005", "meter_single_phase.json")
    assert state(hass, "sensor", "mysite_meter_10005_activePower") == "-22"


async def test_site_meter_totals(hass: HomeAssistant) -> None:
    """Test that the totals of the grid connection are on the site's device."""
    meter = json.loads(load_fixture("meter_three_phase.json"))
    meter["id"] = 14402
    meter["name"] = "Hoofdaansluiting"
    await send_site(hass)
    await send(hass, "mysite/electricitymeters/14402", json.dumps(meter))
    registry = er.async_get(hass)
    imported = registry.async_get(
        entity_id(hass, "sensor", "mysite_site_34901_grid_energy_imported_total")
    )
    assert imported is not None
    site = device(hass, (DOMAIN, "mysite_site_34901"))
    assert site is not None
    assert imported.device_id == site.id
    assert hass.states.get(imported.entity_id).state == str(  # type: ignore[union-attr]
        meter["measurements"]["energyImported"]
    )
    assert entity_id(hass, "sensor", "mysite_site_34901_grid_energy_exported_total")
    # The meter keeps its other values, without the totals.
    assert entity_id(hass, "sensor", "mysite_meter_14402_activePower")
    assert not registry.async_get_entity_id(
        "sensor", DOMAIN, "mysite_meter_14402_energyImported"
    )


async def test_charger_meter_on_charge_point(hass: HomeAssistant) -> None:
    """Test that a charger's meter and circuit belong to its charge point."""
    meter = json.loads(load_fixture("meter_charger.json"))
    meter["name"] = "Lader 06"
    circuit = json.loads(load_fixture("circuit.json"))
    circuit["electricityMeterId"] = meter["id"]
    registry = er.async_get(hass)
    await send_site(hass)
    await send(hass, "mysite/electricitymeters/30753", json.dumps(meter))
    # The meter waits for the charge point with the same name.
    assert not registry.async_get_entity_id(
        "sensor", DOMAIN, "mysite_chargepoint_19463_energyImported"
    )
    await send(hass, "mysite/chargepoints/19463", "chargepoint_connected.json")
    await send(hass, "mysite/electricitymeters/30753", json.dumps(meter))
    await send(hass, "mysite/circuits/19923/live", json.dumps(circuit))

    charger = device(hass, (DOMAIN, "mysite_chargepoint_19463"))
    assert charger is not None
    assert charger.name == "Lader 06"
    assert charger.manufacturer == "Zaptec"
    for unique_id in (
        "mysite_chargepoint_19463_status",
        "mysite_chargepoint_19463_energyImported",
        "mysite_chargepoint_19463_circuit_current_l1",
    ):
        entry = registry.async_get(entity_id(hass, "sensor", unique_id))
        assert entry is not None
        assert entry.device_id == charger.id
    assert device(hass, (DOMAIN, "mysite_meter_30753")) is None


async def test_charge_point(hass: HomeAssistant) -> None:
    """Test a charge point with a vehicle and one without."""
    await send(hass, "mysite/chargepoints/19463", "chargepoint_connected.json")
    await send(hass, "mysite/chargepoints/55602", "chargepoint_available.json")
    assert state(hass, "sensor", "mysite_chargepoint_19463_status") == "suspended_by_ev"
    assert state(hass, "sensor", "mysite_chargepoint_19463_user") == "Alice"
    assert (
        state(hass, "sensor", "mysite_chargepoint_19463_session_start")
        == "2026-11-04T06:41:24+00:00"
    )
    assert (
        state(hass, "sensor", "mysite_chargepoint_19463_session_end") == STATE_UNKNOWN
    )
    assert state(hass, "sensor", "mysite_chargepoint_55602_status") == "available"
    # The name of the last user stays in the data, but is not shown.
    assert state(hass, "sensor", "mysite_chargepoint_55602_user") == STATE_UNKNOWN


async def test_energy_manager(hass: HomeAssistant) -> None:
    """Test the sensors of the energy manager."""
    await send(hass, "mysite/energymanagers/11376/state", "energy_manager.json")
    assert (
        state(hass, "sensor", "mysite_energymanager_11376_optimization_goal")
        == "scheduled_charging"
    )
    assert (
        state(hass, "sensor", "mysite_energymanager_11376_grid_power") != STATE_UNKNOWN
    )


async def test_space_filters_impossible_values(hass: HomeAssistant) -> None:
    """Test that impossible values are unknown and the others are shown."""
    await send(hass, "mysite/spaces/11468/live", "space_invalid.json")
    assert state(hass, "sensor", "mysite_space_11468_temperature") == STATE_UNKNOWN
    assert state(hass, "sensor", "mysite_space_11468_humidity") == STATE_UNKNOWN
    assert state(hass, "sensor", "mysite_space_11468_co2") == "409"

    await send(hass, "mysite/spaces/45472/live", "space.json")
    assert state(hass, "sensor", "mysite_space_45472_temperature") == "21.3"
    assert state(hass, "sensor", "mysite_space_45472_air_quality") == "good"


async def test_system(hass: HomeAssistant) -> None:
    """Test the sensors of the server."""
    await send(hass, "mysite/system", "system.json")
    assert state(hass, "sensor", "mysite_system_cpu_usage") == "18"
    assert (
        state(hass, "sensor", "mysite_system_last_backup")
        == "2026-11-04T00:00:00+00:00"
    )
    found = device(hass, (DOMAIN, "mysite_system"))
    assert found is not None
    assert found.sw_version == "1.0"


async def test_system_started_from_received_time(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Test that the start time is computed from when the data arrived."""
    freezer.move_to("2026-11-04T16:00:30+00:00")
    payload = json.loads(load_fixture("system.json"))
    payload["systemUptimeSeconds"] = 3600
    await send(hass, "mysite/system", json.dumps(payload))
    assert state(hass, "sensor", "mysite_system_system_started") == (
        "2026-11-04T15:00:00+00:00"
    )
    # A later state write does not move the start time.
    freezer.tick(timedelta(minutes=10))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert state(hass, "sensor", "mysite_system_system_started") == (
        "2026-11-04T15:00:00+00:00"
    )


async def test_milesight(hass: HomeAssistant) -> None:
    """Test a Milesight sensor; its battery voltage is shown in volt."""
    await send(hass, "milesight/uplink/a81758fffe054f0d", "milesight.json")
    assert (
        state(hass, "sensor", "mysite_milesight_a81758fffe054f0d_temperature") == "21.3"
    )
    assert (
        state(hass, "sensor", "mysite_milesight_a81758fffe054f0d_battery_voltage")
        == "3.629"
    )


async def test_milesight_light(hass: HomeAssistant) -> None:
    """Test the illuminance of a Milesight sensor that measures light."""
    await send(hass, "milesight/uplink/a81758fffe054f0c", "milesight_light.json")
    assert (
        state(hass, "sensor", "mysite_milesight_a81758fffe054f0c_illuminance") == "503"
    )


async def test_translations(hass: HomeAssistant) -> None:
    """Test that every entity and device has a translated name."""
    await send_all(hass)
    for entry in er.async_entries_for_config_entry(
        er.async_get(hass), hass.config_entries.async_entries(DOMAIN)[0].entry_id
    ):
        if entry.translation_key is not None:
            names = STRINGS["entity"][entry.domain]
            assert entry.translation_key in names, entry.translation_key
    config_entry = hass.config_entries.async_entries(DOMAIN)[0]
    for device_entry in dr.async_entries_for_config_entry(
        dr.async_get(hass), config_entry.entry_id
    ):
        assert device_entry.name, device_entry.identifiers
