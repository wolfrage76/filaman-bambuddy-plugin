"""Pending assign follows a bay that is emptied, then loaded again."""

import sys
import types
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parents[1] / "bambuddy"
if "bambuddy" not in sys.modules:
    _pkg = types.ModuleType("bambuddy")
    _pkg.__path__ = [str(_PKG_DIR)]
    _pkg.__package__ = "bambuddy"
    sys.modules["bambuddy"] = _pkg

from bambuddy.driver import Driver  # noqa: E402


def _driver() -> Driver:
    driver = Driver.__new__(Driver)
    driver.printer_id = 13
    driver._pending_spool_id = 151
    driver._pending_rfid_hex = None
    driver._pending_filament_data = {"type": "PLA"}
    driver._current_slots = []
    driver._current_ams_units = []
    driver._slot_to_tray_uuid = {}
    driver._slot_params_cache = {}
    driver._slot_to_filaman_spool = {}
    driver._slot_configure_inflight = {}
    driver._slot_configure_gen = {}
    driver._slot_last_sent = {}
    driver._pending_slot_snapshot = {
        "1-3": {
            "present": True,
            "tray_type": "PETG",
            "tray_color": "050503FF",
            "state": 11,
            "tag_uid": "",
        }
    }
    driver.fired = []
    driver.emitted = []
    driver.send_filament_to_tray = lambda ams_id, tray_id, data: driver.fired.append(
        (ams_id, tray_id, data)
    )

    def _clear():
        driver._pending_spool_id = None
        driver._pending_slot_snapshot = None

    driver._clear_pending_peers = _clear
    driver._cancel_sticky_task = lambda slot_index: None
    driver._bump_slot_configure_gen = lambda slot_index: None
    driver._schedule_sticky_reassert = lambda *a, **k: None
    driver.emit = lambda event: driver.emitted.append(event)
    return driver


def _loaded(**extra) -> dict:
    tray = {
        "id": 3,
        "tray_type": "PETG",
        "tray_color": "050503FF",
        "state": 11,
        "exists": True,
        "tag_uid": "",
    }
    tray.update(extra)
    return tray


def _empty() -> dict:
    return {"id": 3, "state": 0, "exists": False}


def _frame(tray: dict) -> dict:
    return {"ams": [{"id": 1, "tray": [tray]}]}


def _vt_frame(vt: dict) -> dict:
    return {"vt_tray": [vt]}


# -- matcher-level -----------------------------------------------------------


def test_same_profile_after_scan_is_not_an_insert():
    driver = _driver()
    assert driver._try_match_pending_tray("1-3", _loaded()) == (False, "")


def test_empty_tray_never_matches():
    driver = _driver()
    assert driver._try_match_pending_tray("1-3", _empty()) == (False, "")


def test_bay_already_empty_at_scan_matches_when_a_spool_appears():
    driver = _driver()
    driver._pending_slot_snapshot["1-3"]["present"] = False
    assert driver._try_match_pending_tray("1-3", _loaded()) == (True, "slot-appeared")


def test_note_empty_is_idempotent_and_creates_missing_entries():
    driver = _driver()
    driver._note_pending_slot_empty("1-3")
    driver._note_pending_slot_empty("1-3")
    assert driver._pending_slot_snapshot["1-3"]["present"] is False
    driver._note_pending_slot_empty("0-0")
    assert driver._pending_slot_snapshot["0-0"]["present"] is False


# -- _process_slots integration ----------------------------------------------


def test_unchanged_loaded_bay_does_not_fire():
    driver = _driver()
    driver._process_slots(_frame(_loaded()))
    driver._process_slots(_frame(_loaded()))
    assert driver.fired == []
    assert driver._pending_spool_id == 151


def test_swap_with_stale_profile_fires_once():
    driver = _driver()
    driver._process_slots(_frame(_loaded()))
    driver._process_slots(_frame(_empty()))
    assert driver._pending_slot_snapshot["1-3"]["present"] is False
    assert driver.fired == []

    # Printer still reports the old PETG profile for the new spool.
    driver._process_slots(_frame(_loaded()))
    assert driver.fired == [(1, 3, {"type": "PLA"})]
    assert driver._slot_to_filaman_spool["1-3"] == 151
    assert driver._pending_spool_id is None

    # Nothing left pending; further frames are inert.
    driver._process_slots(_frame(_loaded()))
    assert len(driver.fired) == 1


def test_empty_bay_is_not_tracked_without_a_pending_scan():
    driver = _driver()
    driver._pending_spool_id = None
    driver._process_slots(_frame(_empty()))
    assert driver._pending_slot_snapshot["1-3"]["present"] is True


def test_external_tray_swap_fires_once():
    driver = _driver()
    driver._pending_slot_snapshot = {
        "255-0": {
            "present": True,
            "tray_type": "PETG",
            "tray_color": "050503FF",
            "state": 11,
            "tag_uid": "",
        }
    }
    loaded = {"id": 254, "tray_type": "PETG", "tray_color": "050503FF", "state": 11}
    driver._process_slots(_vt_frame(loaded))
    assert driver.fired == []
    driver._process_slots(_vt_frame({"id": 254, "tray_type": "", "state": 0}))
    assert driver._pending_slot_snapshot["255-0"]["present"] is False
    assert driver.fired == []
    driver._process_slots(_vt_frame(loaded))
    assert len(driver.fired) == 1
    assert driver.fired[0][0] == 255
    assert driver._pending_spool_id is None
