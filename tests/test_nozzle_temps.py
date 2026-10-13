"""Nozzle temperatures sent to an AMS slot.

Stored printer params win. With none stored, a same-material live tray is
kept. Otherwise the material default is used — not the PLA 190–230 range.
"""

import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

_PKG_DIR = Path(__file__).resolve().parents[1] / "bambuddy"
if "bambuddy" not in sys.modules:
    _pkg = types.ModuleType("bambuddy")
    _pkg.__path__ = [str(_PKG_DIR)]
    _pkg.__package__ = "bambuddy"
    sys.modules["bambuddy"] = _pkg

from bambuddy.driver import Driver, resolve_nozzle_temps  # noqa: E402


def test_stored_printer_params_win_over_live_tray():
    temps = resolve_nozzle_temps(
        {"bambu_nozzle_temp_min": "200", "bambu_nozzle_temp_max": "240"},
        "PETG",
        {"tray_type": "PETG", "nozzle_temp_min": 190, "nozzle_temp_max": 230},
    )
    assert temps == (200, 240, False)


def test_bambu_params_win_over_placeholder_nozzle_keys():
    temps = resolve_nozzle_temps(
        {
            "bambu_nozzle_temp_min": "240",
            "nozzle_temp_min": 190,
            "bambu_nozzle_temp_max": "270",
            "nozzle_temp_max": 230,
        },
        "ABS",
        None,
    )
    assert temps == (240, 270, False)


def test_same_material_live_tray_is_kept_when_nothing_is_stored():
    temps = resolve_nozzle_temps(
        {"material_type": "PETG"},
        "PETG",
        {"tray_type": "PETG", "nozzle_temp_min": 225, "nozzle_temp_max": 255},
    )
    assert temps == (225, 255, True)


def test_swap_does_not_keep_the_previous_materials_temps():
    temps = resolve_nozzle_temps(
        {},
        "PETG",
        {"tray_type": "PLA", "nozzle_temp_min": 190, "nozzle_temp_max": 230},
    )
    assert temps == (220, 250, False)


def test_material_defaults_when_no_stored_or_live_temps():
    assert resolve_nozzle_temps({}, "PLA", None)[:2] == (190, 230)
    assert resolve_nozzle_temps({}, "PLA+", None)[:2] == (190, 230)
    assert resolve_nozzle_temps({}, "ASA", None)[:2] == (240, 270)
    assert resolve_nozzle_temps({}, "NYLON", None)[:2] == (240, 280)
    assert resolve_nozzle_temps({}, "PC", None)[:2] == (260, 300)
    assert resolve_nozzle_temps({}, "UNKNOWN", None)[:2] == (190, 230)


def test_missing_side_is_filled_from_the_live_tray():
    temps = resolve_nozzle_temps(
        {"nozzle_temp_min": 210},
        "ASA",
        {"tray_type": "ASA", "nozzle_temp_min": 200, "nozzle_temp_max": 260},
    )
    assert temps == (210, 260, True)


def _driver() -> Driver:
    driver = Driver.__new__(Driver)
    driver.printer_id = 7
    driver._last_bambuddy_status = {"gcode_state": "IDLE"}
    driver._slot_to_filaman_spool = {"0-0": 10, "0-1": 11}
    driver._pending_reconfigure_after_print = False
    driver._peer_drivers = lambda: [driver]
    driver._filament_data_for_spool = AsyncMock(return_value={"id": 10})
    driver._send_assignment = AsyncMock()
    return driver


@pytest.mark.asyncio
async def test_profile_edit_reconfigures_only_the_slot_holding_the_spool():
    driver = _driver()

    count = await driver._reconfigure_slots_holding_spools(
        [10], reason="spool_profile"
    )

    assert count == 1
    driver._send_assignment.assert_awaited_once()
    assert driver._send_assignment.await_args.args[:2] == (0, 0)
    assert driver._pending_reconfigure_after_print is False


@pytest.mark.asyncio
async def test_profile_edit_during_print_defers_until_idle():
    driver = _driver()
    driver._last_bambuddy_status = {"gcode_state": "RUNNING"}

    count = await driver._reconfigure_slots_holding_spools(
        [10], reason="spool_profile"
    )

    assert count == 0
    driver._send_assignment.assert_not_awaited()
    assert driver._pending_reconfigure_after_print is True


@pytest.mark.asyncio
async def test_profile_edit_reconfigures_the_peer_printer_holding_the_spool():
    local = _driver()
    peer = _driver()
    peer.printer_id = 8
    peer._slot_to_filaman_spool = {"1-2": 10}
    local._slot_to_filaman_spool = {}
    local._peer_drivers = lambda: [local, peer]
    peer._peer_drivers = lambda: [local, peer]

    count = await local._reconfigure_slots_holding_spools(
        [10], reason="spool_profile"
    )

    assert count == 1
    local._send_assignment.assert_not_awaited()
    peer._send_assignment.assert_awaited_once()
    assert peer._send_assignment.await_args.args[:2] == (1, 2)
