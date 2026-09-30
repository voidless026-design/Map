# SPDX-License-Identifier: MIT
"""The USB gamepad the Fruit Jam shows to the PC for the Stick Drift Fix app.

``boot.py`` must call ``enable()``: USB devices can only be changed before the PC
sees the board, so this cannot happen in ``code.py``. The keyboard, mouse and
media-key devices CircuitPython normally provides stay enabled, so other Fruit Jam
apps keep working.

Report layout (report ID 4, 13 bytes):
  buttons   uint16  bits 0-15 = buttons 1-16
  hat       4 bits  0 = up, clockwise to 7, 8 = centered (+ 4 bits padding)
  X, Y      int16   left stick, -32767..32767, Y down is positive (HID convention)
  Rx, Ry    int16   right stick
  Z, Rz     uint8   left and right trigger, 0..255
"""

import struct

REPORT_ID = 4
REPORT_LENGTH = 13
AXIS_MAX = 32767

# fmt: off
REPORT_DESCRIPTOR = bytes((
    0x05, 0x01,        # Usage Page (Generic Desktop)
    0x09, 0x05,        # Usage (Game Pad)
    0xA1, 0x01,        # Collection (Application)
    0x85, REPORT_ID,   #   Report ID (4)
    0x05, 0x09,        #   Usage Page (Button)
    0x19, 0x01,        #   Usage Minimum (Button 1)
    0x29, 0x10,        #   Usage Maximum (Button 16)
    0x15, 0x00,        #   Logical Minimum (0)
    0x25, 0x01,        #   Logical Maximum (1)
    0x75, 0x01,        #   Report Size (1)
    0x95, 0x10,        #   Report Count (16)
    0x81, 0x02,        #   Input (Data, Variable, Absolute)
    0x05, 0x01,        #   Usage Page (Generic Desktop)
    0x09, 0x39,        #   Usage (Hat Switch)
    0x15, 0x00,        #   Logical Minimum (0)
    0x25, 0x07,        #   Logical Maximum (7)
    0x35, 0x00,        #   Physical Minimum (0)
    0x46, 0x3B, 0x01,  #   Physical Maximum (315)
    0x65, 0x14,        #   Unit (Degrees)
    0x75, 0x04,        #   Report Size (4)
    0x95, 0x01,        #   Report Count (1)
    0x81, 0x42,        #   Input (Data, Variable, Absolute, Null State)
    0x65, 0x00,        #   Unit (None)
    0x45, 0x00,        #   Physical Maximum (0) - back to "same as logical"
    0x75, 0x04,        #   Report Size (4)
    0x95, 0x01,        #   Report Count (1)
    0x81, 0x03,        #   Input (Constant) - padding
    0x09, 0x30,        #   Usage (X)
    0x09, 0x31,        #   Usage (Y)
    0x09, 0x33,        #   Usage (Rx)
    0x09, 0x34,        #   Usage (Ry)
    0x16, 0x01, 0x80,  #   Logical Minimum (-32767)
    0x26, 0xFF, 0x7F,  #   Logical Maximum (32767)
    0x75, 0x10,        #   Report Size (16)
    0x95, 0x04,        #   Report Count (4)
    0x81, 0x02,        #   Input (Data, Variable, Absolute)
    0x09, 0x32,        #   Usage (Z)
    0x09, 0x35,        #   Usage (Rz)
    0x15, 0x00,        #   Logical Minimum (0)
    0x26, 0xFF, 0x00,  #   Logical Maximum (255)
    0x75, 0x08,        #   Report Size (8)
    0x95, 0x02,        #   Report Count (2)
    0x81, 0x02,        #   Input (Data, Variable, Absolute)
    0xC0,              # End Collection
))
# fmt: on


def enable():
    """Call from boot.py. Adds the gamepad next to CircuitPython's default devices."""
    import usb_hid

    gamepad = usb_hid.Device(
        report_descriptor=REPORT_DESCRIPTOR,
        usage_page=0x01,  # Generic Desktop
        usage=0x05,  # Game Pad
        report_ids=(REPORT_ID,),
        in_report_lengths=(REPORT_LENGTH,),
        out_report_lengths=(0,),
    )
    usb_hid.enable(
        (
            usb_hid.Device.KEYBOARD,
            usb_hid.Device.MOUSE,
            usb_hid.Device.CONSUMER_CONTROL,
            gamepad,
        )
    )


def find_device(devices):
    """Return the gamepad from ``usb_hid.devices``, or None if boot.py didn't enable it."""
    for device in devices:
        if device.usage_page == 0x01 and device.usage == 0x05:
            return device
    return None


def _axis(value):
    return -AXIS_MAX if value < -AXIS_MAX else AXIS_MAX if value > AXIS_MAX else int(value)


def pack_report(buttons, hat, lx, ly, rx, ry, lt, rt):
    """Build a report. Sticks come in Xbox style (up is positive) and are flipped here."""
    return struct.pack(
        "<HBhhhhBB",
        buttons & 0xFFFF,
        hat & 0x0F,
        _axis(lx),
        _axis(-ly),
        _axis(rx),
        _axis(-ry),
        max(0, min(255, lt)),
        max(0, min(255, rt)),
    )


NEUTRAL_REPORT = pack_report(0, 8, 0, 0, 0, 0, 0, 0)
