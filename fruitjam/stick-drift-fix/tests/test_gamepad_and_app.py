import importlib.util
import struct
import sys
import types
from pathlib import Path

import pytest
import stick_drift_gamepad as gamepad
import xbox_pad

APP_DIR = Path(__file__).resolve().parents[1] / "CIRCUITPY" / "apps" / "Stick_Drift_Fix"


def input_bits(descriptor):
    """Walk a HID report descriptor and add up the bits of every Input item."""
    bits = size = count = 0
    i = 0
    while i < len(descriptor):
        prefix = descriptor[i]
        length = (0, 1, 2, 4)[prefix & 0x03]
        value = int.from_bytes(descriptor[i + 1:i + 1 + length], "little")
        tag = prefix & 0xFC
        if tag == 0x74:
            size = value
        elif tag == 0x94:
            count = value
        elif tag == 0x80:
            bits += size * count
        i += 1 + length
    return bits


def test_descriptor_matches_report_length():
    assert input_bits(gamepad.REPORT_DESCRIPTOR) == gamepad.REPORT_LENGTH * 8
    assert len(gamepad.NEUTRAL_REPORT) == gamepad.REPORT_LENGTH


def test_report_layout_flips_y_and_clamps():
    report = gamepad.pack_report(0b101, 2, 100, 200, -32768, 32767, 300, -5)
    buttons, hat, lx, ly, rx, ry, lt, rt = struct.unpack("<HBhhhhBB", report)
    assert (buttons, hat) == (0b101, 2)
    assert (lx, ly) == (100, -200)  # up on the stick is negative Y in HID
    assert (rx, ry) == (-32767, -32767)
    assert (lt, rt) == (255, 0)


def test_find_device_picks_the_gamepad():
    class Dev:
        def __init__(self, page, usage):
            self.usage_page, self.usage = page, usage

    keyboard, pad = Dev(0x01, 0x06), Dev(0x01, 0x05)
    assert gamepad.find_device((keyboard, pad)) is pad
    assert gamepad.find_device((keyboard,)) is None


# --- The app loop, end to end with a fake controller --------------------------------


class FakeOutput:
    def __init__(self):
        self.reports = []

    def send_report(self, report):
        self.reports.append(bytes(report))

    def last(self):
        return struct.unpack("<HBhhhhBB", self.reports[-1])


class ScriptedPad:
    """A connected controller that reports one scripted state per poll."""

    kind = xbox_pad.KIND_360
    name = "Test pad"

    def __init__(self, states):
        self.states = list(states)
        self.state = xbox_pad.PadState()

    def poll(self):
        if not self.states:
            return False
        item = self.states.pop(0)
        if isinstance(item, Exception):
            raise item
        self.state.rx, self.state.ry = item
        self.state.has_report = True
        return True


@pytest.fixture
def app_module(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "stick_drift_app", APP_DIR / "code.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    clock = {"ms": 0}
    monkeypatch.setattr(module, "now_ms", lambda: clock["ms"])
    monkeypatch.setattr(module.time, "sleep", lambda s: None)
    monkeypatch.setattr(module, "make_buttons", lambda: None)
    module.clock = clock
    return module


def run(app, module, pad_states, step_ms=4):
    pad = ScriptedPad(pad_states)
    app.pad = pad
    while pad.states:
        app.step()
        module.clock["ms"] += step_ms


def test_drift_is_removed_and_real_aim_passes_through(app_module):
    out = FakeOutput()
    app = app_module.DriftFix(out)
    drift = [(2600 + (i % 9) * 80, -2100 + (i % 4) * 120) for i in range(700)]

    app.start_calibration()
    run(app, app_module, drift)  # 2.8 s of hands-off drift: calibration finishes
    assert app.calibrating is None
    assert app.right.center_x > 2000 and app.right.deadzone >= app_module.MIN_DEADZONE

    run(app, app_module, drift[:50])
    assert out.last()[4:6] == (0, 0)  # the drift never reaches the PC

    run(app, app_module, [(32767, -2100)])
    rx, ry = out.last()[4:6]
    assert rx == 32767 and abs(ry) < 300  # full right still means full right

    run(app, app_module, [(12000, 15000)])
    rx, ry = out.last()[4:6]
    assert rx > 0 and ry < 0  # up-right on the stick = right and HID "up"


def test_touched_stick_keeps_previous_calibration(app_module):
    out = FakeOutput()
    app = app_module.DriftFix(out)
    before = (app.right.center_x, app.right.deadzone)
    app.start_calibration()
    run(app, app_module, [(0, 0), (25000, 0)] * 300)
    assert app.calibrating is None
    assert (app.right.center_x, app.right.deadzone) == before


def test_fix_can_be_switched_off_for_comparison(app_module):
    out = FakeOutput()
    app = app_module.DriftFix(out)
    app.enabled = False
    run(app, app_module, [(1500, 900)])
    assert out.last()[4:6] == (1500, -900)


def test_unplugging_releases_the_sticks_on_the_pc(app_module):
    out = FakeOutput()
    app = app_module.DriftFix(out)
    run(app, app_module, [(30000, 30000), OSError("device gone")])
    assert app.pad is None
    assert out.reports[-1] == gamepad.NEUTRAL_REPORT


def test_missing_boot_setup_is_explained(app_module, monkeypatch, capsys):
    monkeypatch.setattr(sys.modules["usb_hid"], "devices", (), raising=False)

    class Stop(Exception):
        pass

    def stop(_):
        raise Stop

    monkeypatch.setattr(app_module.time, "sleep", stop)
    monkeypatch.setitem(sys.modules, "neopixel", types.ModuleType("neopixel"))
    with pytest.raises(Stop):
        app_module.main()
    assert "stick_drift_gamepad.enable()" in capsys.readouterr().out


def test_silent_controller_ends_calibration_with_a_hint(app_module, capsys):
    out = FakeOutput()
    app = app_module.DriftFix(out)
    app.pad = ScriptedPad([])  # connected, but has not sent a report yet
    app.start_calibration()
    for _ in range(600):
        app.step()
        app_module.clock["ms"] += 4
    assert app.calibrating is None
    assert "No input from the controller yet" in capsys.readouterr().out
