"""Run the Fruit Jam code on a desktop: put the app and lib folders on the path and
stand in for the CircuitPython-only modules (board, usb_hid)."""

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "CIRCUITPY"
sys.path[:0] = [str(ROOT / "apps" / "Stick_Drift_Fix"), str(ROOT / "lib")]

if "board" not in sys.modules:
    board = types.ModuleType("board")
    board.NEOPIXEL = board.BUTTON1 = board.BUTTON2 = board.BUTTON3 = object()
    sys.modules["board"] = board

if "usb_hid" not in sys.modules:
    usb_hid = types.ModuleType("usb_hid")
    usb_hid.devices = ()
    sys.modules["usb_hid"] = usb_hid
