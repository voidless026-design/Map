# SPDX-License-Identifier: MIT
"""Wired Xbox controller driver for CircuitPython USB host (Fruit Jam's USB-A ports).

Supports:
  * Xbox 360 wired pads and third-party pads in "XInput" mode
    (vendor interface, subclass 0x5D, protocol 0x01).
  * Xbox One / Series X|S / Elite pads over a USB cable (the GIP protocol,
    vendor interface, subclass 0x47, protocol 0xD0).

Report layouts and the start-up packets follow the Linux ``xpad`` driver.
The parsing functions are pure Python so they can be tested on a desktop.
"""

import array
import struct

try:
    import usb.core

    _USBTimeoutError = usb.core.USBTimeoutError
except (ImportError, AttributeError):  # desktop tests
    usb = None

    class _USBTimeoutError(Exception):
        pass


KIND_360 = "Xbox 360"
KIND_GIP = "Xbox One/Series"

# Button bits in the order the Fruit Jam reports them to the PC (buttons 1-11).
BTN_A = 1 << 0
BTN_B = 1 << 1
BTN_X = 1 << 2
BTN_Y = 1 << 3
BTN_LB = 1 << 4
BTN_RB = 1 << 5
BTN_VIEW = 1 << 6  # "Back" on a 360 pad
BTN_MENU = 1 << 7  # "Start" on a 360 pad
BTN_LS = 1 << 8
BTN_RS = 1 << 9
BTN_GUIDE = 1 << 10

HAT_CENTERED = 8

_DESC_INTERFACE = 0x04
_DESC_ENDPOINT = 0x05
_DESC_CONFIGURATION = 0x02

# GIP (Xbox One) packet types and flags.
_GIP_ACK = 0x01
_GIP_ANNOUNCE = 0x02
_GIP_POWER = 0x05
_GIP_AUTH = 0x06
_GIP_GUIDE = 0x07
_GIP_LED = 0x0A
_GIP_INPUT = 0x20
_GIP_OPT_ACK = 0x10
_GIP_OPT_INTERNAL = 0x20


class PadState:
    """Latest controller input. Sticks are raw -32768..32767, up is positive."""

    def __init__(self):
        self.buttons = 0
        self.hat = HAT_CENTERED
        self.lx = self.ly = self.rx = self.ry = 0
        self.lt = self.rt = 0  # 0..255
        self.has_report = False


def dpad_to_hat(up, down, left, right):
    """Convert D-pad buttons to a HID hat value (0 = up, clockwise, 8 = centered)."""
    if up and not down:
        return 1 if right and not left else 7 if left and not right else 0
    if down and not up:
        return 3 if right and not left else 5 if left and not right else 4
    if right and not left:
        return 2
    if left and not right:
        return 6
    return HAT_CENTERED


def _bit(value, index):
    return bool(value & (1 << index))


def parse_360_report(data, state):
    """Parse an Xbox 360 input report into ``state``. Returns True if it was input."""
    if len(data) < 14 or data[0] != 0x00 or data[1] < 0x14:
        return False
    b2, b3 = data[2], data[3]
    buttons = 0
    if _bit(b3, 4):
        buttons |= BTN_A
    if _bit(b3, 5):
        buttons |= BTN_B
    if _bit(b3, 6):
        buttons |= BTN_X
    if _bit(b3, 7):
        buttons |= BTN_Y
    if _bit(b3, 0):
        buttons |= BTN_LB
    if _bit(b3, 1):
        buttons |= BTN_RB
    if _bit(b2, 5):
        buttons |= BTN_VIEW
    if _bit(b2, 4):
        buttons |= BTN_MENU
    if _bit(b2, 6):
        buttons |= BTN_LS
    if _bit(b2, 7):
        buttons |= BTN_RS
    if _bit(b3, 2):
        buttons |= BTN_GUIDE
    state.buttons = buttons
    state.hat = dpad_to_hat(_bit(b2, 0), _bit(b2, 1), _bit(b2, 2), _bit(b2, 3))
    state.lt = data[4]
    state.rt = data[5]
    state.lx, state.ly, state.rx, state.ry = struct.unpack_from("<hhhh", data, 6)
    state.has_report = True
    return True


def parse_gip_input(data, state):
    """Parse an Xbox One/Series input packet (type 0x20). Returns True if it was input."""
    if len(data) < 18 or data[0] != _GIP_INPUT:
        return False
    b4, b5 = data[4], data[5]
    # The Guide button arrives in its own packet; keep whatever it last said.
    buttons = state.buttons & BTN_GUIDE
    if _bit(b4, 4):
        buttons |= BTN_A
    if _bit(b4, 5):
        buttons |= BTN_B
    if _bit(b4, 6):
        buttons |= BTN_X
    if _bit(b4, 7):
        buttons |= BTN_Y
    if _bit(b5, 4):
        buttons |= BTN_LB
    if _bit(b5, 5):
        buttons |= BTN_RB
    if _bit(b4, 3):
        buttons |= BTN_VIEW
    if _bit(b4, 2):
        buttons |= BTN_MENU
    if _bit(b5, 6):
        buttons |= BTN_LS
    if _bit(b5, 7):
        buttons |= BTN_RS
    state.buttons = buttons
    state.hat = dpad_to_hat(_bit(b5, 0), _bit(b5, 1), _bit(b5, 2), _bit(b5, 3))
    left_trigger, right_trigger = struct.unpack_from("<HH", data, 6)
    state.lt = min(left_trigger, 1023) >> 2  # 10-bit -> 8-bit
    state.rt = min(right_trigger, 1023) >> 2
    state.lx, state.ly, state.rx, state.ry = struct.unpack_from("<hhhh", data, 10)
    state.has_report = True
    return True


def parse_gip_guide(data, state):
    """Parse the separate Guide-button packet (type 0x07). Returns True if it was one."""
    if len(data) < 5 or data[0] != _GIP_GUIDE:
        return False
    if data[4] & 0x03:
        state.buttons |= BTN_GUIDE
    else:
        state.buttons &= ~BTN_GUIDE
    return True


def gip_guide_ack(sequence):
    """Acknowledge a Guide packet; without it some pads resend it forever."""
    return bytes(
        (_GIP_ACK, _GIP_OPT_INTERNAL, sequence, 0x09,
         0x00, _GIP_GUIDE, _GIP_OPT_INTERNAL, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00)
    )


def gip_init_packets(vendor_id, product_id):
    """Start-up packets for a GIP pad, in the order the Linux xpad driver sends them.

    Byte 2 of each packet is a sequence number and is filled in when sent.
    """
    packets = []
    if (vendor_id, product_id) in ((0x0E6F, 0x0165), (0x0F0D, 0x0067)):
        # Titanfall 2 and Hori pads: acknowledge the identify step first.
        packets.append(
            bytes((_GIP_ACK, _GIP_OPT_INTERNAL, 0x00, 0x09,
                   0x00, 0x04, _GIP_OPT_INTERNAL, 0x3A, 0x00, 0x00, 0x00, 0x80, 0x00))
        )
    packets.append(bytes((_GIP_POWER, _GIP_OPT_INTERNAL, 0x00, 0x01, 0x00)))  # power on
    if vendor_id == 0x045E and product_id in (0x02EA, 0x0B00):
        # Xbox One S and Elite Series 2: leave Bluetooth mode.
        packets.append(bytes((_GIP_POWER, _GIP_OPT_INTERNAL, 0x00, 0x0F, 0x06)))
    packets.append(bytes((_GIP_LED, _GIP_OPT_INTERNAL, 0x00, 0x03, 0x00, 0x01, 0x14)))  # LED on
    packets.append(bytes((_GIP_AUTH, _GIP_OPT_INTERNAL, 0x00, 0x02, 0x01, 0x00)))  # auth done
    return packets


def find_xbox_interface(config_descriptor):
    """Find the controller interface in a raw configuration descriptor.

    Returns ``(kind, interface_number, endpoint_in, endpoint_out)`` or None.
    """
    found = None
    i = 0
    total = len(config_descriptor)
    while i + 1 < total:
        length = config_descriptor[i]
        if length < 2:
            break
        kind = config_descriptor[i + 1]
        if kind == _DESC_INTERFACE and i + 8 <= total:
            if found is not None and found[2] is not None:
                break  # the next interface starts; the one we want is complete
            number = config_descriptor[i + 2]
            alternate = config_descriptor[i + 3]
            iface = tuple(config_descriptor[i + 5:i + 8])
            found = None
            if alternate == 0 and iface == (0xFF, 0x5D, 0x01):
                found = [KIND_360, number, None, None]
            elif alternate == 0 and iface == (0xFF, 0x47, 0xD0):
                found = [KIND_GIP, number, None, None]
        elif kind == _DESC_ENDPOINT and found is not None and i + 3 < total:
            address = config_descriptor[i + 2]
            interrupt = (config_descriptor[i + 3] & 0x03) == 0x03
            if interrupt and address & 0x80 and found[2] is None:
                found[2] = address
            elif interrupt and not address & 0x80 and found[3] is None:
                found[3] = address
        i += length
    if found is None or found[2] is None:
        return None
    return tuple(found)


def read_config_descriptor(device):
    """Read the full configuration descriptor with two GET_DESCRIPTOR requests."""
    header = array.array("B", [0] * 4)
    device.ctrl_transfer(0x80, 0x06, _DESC_CONFIGURATION << 8, 0, header)
    total_length = header[2] | (header[3] << 8)
    full = array.array("B", [0] * total_length)
    device.ctrl_transfer(0x80, 0x06, _DESC_CONFIGURATION << 8, 0, full)
    return bytes(full)


class XboxPad:
    """One connected wired Xbox controller."""

    def __init__(self, device, kind, interface, endpoint_in, endpoint_out, timeout_ms=8):
        self.device = device
        self.kind = kind
        self.interface = interface
        self.endpoint_in = endpoint_in
        self.endpoint_out = endpoint_out
        self.timeout_ms = timeout_ms
        self.state = PadState()
        self._buffer = array.array("B", [0] * 64)
        self._sequence = 0
        self._quiet_timeouts = True  # CircuitPython builds with raise_on_timeout=

    @property
    def name(self):
        product = None
        try:
            product = self.device.product
        except Exception:
            pass
        return product or self.kind

    def start(self):
        """Claim the controller and send its start-up packets."""
        try:
            if self.device.is_kernel_driver_active(self.interface):
                self.device.detach_kernel_driver(self.interface)
        except Exception:
            pass  # vendor interfaces normally have no driver attached
        self.device.set_configuration()
        if self.endpoint_out is None:
            return
        if self.kind == KIND_GIP:
            for packet in gip_init_packets(self.device.idVendor, self.device.idProduct):
                self._send_gip(packet)
        else:
            try:
                # Player-1 light on, instead of blinking forever.
                self.device.write(self.endpoint_out, bytes((0x01, 0x03, 0x06)), 100)
            except Exception:
                pass

    def _send_gip(self, packet):
        packet = bytearray(packet)
        packet[2] = self._sequence
        self._sequence = (self._sequence + 1) & 0xFF
        try:
            self.device.write(self.endpoint_out, packet, 100)
        except _USBTimeoutError:
            pass

    def _read(self):
        if self._quiet_timeouts:
            try:
                return self.device.read(
                    self.endpoint_in, self._buffer, self.timeout_ms, raise_on_timeout=False
                )
            except TypeError:
                self._quiet_timeouts = False  # older CircuitPython: timeouts raise
        try:
            return self.device.read(self.endpoint_in, self._buffer, self.timeout_ms)
        except _USBTimeoutError:
            return 0

    def poll(self):
        """Read one packet. Returns True if the input state changed.

        Raises ``usb.core.USBError`` when the controller is unplugged.
        """
        count = self._read()
        if not count:
            return False
        data = memoryview(self._buffer)[:count]
        if self.kind == KIND_360:
            return parse_360_report(data, self.state)
        if data[0] == _GIP_INPUT:
            return parse_gip_input(data, self.state)
        if data[0] == _GIP_GUIDE:
            if count > 2 and data[1] == (_GIP_OPT_ACK | _GIP_OPT_INTERNAL) and self.endpoint_out:
                try:
                    self.device.write(self.endpoint_out, gip_guide_ack(data[2]), 100)
                except _USBTimeoutError:
                    pass
            return parse_gip_guide(data, self.state)
        if data[0] == _GIP_ANNOUNCE and self.endpoint_out is not None:
            # Some pads only listen after they announce themselves: send start-up again.
            for packet in gip_init_packets(self.device.idVendor, self.device.idProduct):
                self._send_gip(packet)
        return False


def find_pad(timeout_ms=8):
    """Return a started XboxPad for the first wired Xbox controller found, or None."""
    for device in usb.core.find(find_all=True) or ():
        try:
            match = find_xbox_interface(read_config_descriptor(device))
        except Exception:
            continue
        if match is None:
            continue
        kind, interface, endpoint_in, endpoint_out = match
        pad = XboxPad(device, kind, interface, endpoint_in, endpoint_out, timeout_ms)
        pad.start()
        return pad
    return None
