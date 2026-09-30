import struct

import pytest
import xbox_pad
from xbox_pad import (
    BTN_A,
    BTN_GUIDE,
    BTN_LB,
    BTN_MENU,
    BTN_RS,
    BTN_VIEW,
    BTN_Y,
    HAT_CENTERED,
    KIND_360,
    KIND_GIP,
    PadState,
    XboxPad,
    dpad_to_hat,
    find_xbox_interface,
    gip_init_packets,
    parse_360_report,
    parse_gip_guide,
    parse_gip_input,
)

# Configuration descriptors shaped like the real ones (vendor blobs included).
X360_CONFIG = bytes(
    [0x09, 0x02, 0x99, 0x00, 0x04, 0x01, 0x00, 0xA0, 0xFA]
    # interface 0: the controller
    + [0x09, 0x04, 0x00, 0x00, 0x02, 0xFF, 0x5D, 0x01, 0x00]
    + [0x11, 0x21] + [0x00] * 15
    + [0x07, 0x05, 0x81, 0x03, 0x20, 0x00, 0x04]
    + [0x07, 0x05, 0x01, 0x03, 0x20, 0x00, 0x08]
    # interface 1: headset (must be ignored)
    + [0x09, 0x04, 0x01, 0x00, 0x04, 0xFF, 0x5D, 0x03, 0x00]
    + [0x07, 0x05, 0x82, 0x03, 0x20, 0x00, 0x02]
)

GIP_CONFIG = bytes(
    [0x09, 0x02, 0x60, 0x00, 0x03, 0x01, 0x00, 0xA0, 0xFA]
    # interface 0: controller data
    + [0x09, 0x04, 0x00, 0x00, 0x02, 0xFF, 0x47, 0xD0, 0x00]
    + [0x07, 0x05, 0x02, 0x03, 0x40, 0x00, 0x04]
    + [0x07, 0x05, 0x82, 0x03, 0x40, 0x00, 0x04]
    # interface 1: audio, alternate settings 0 and 1
    + [0x09, 0x04, 0x01, 0x00, 0x00, 0xFF, 0x47, 0xD0, 0x00]
    + [0x09, 0x04, 0x01, 0x01, 0x02, 0xFF, 0x47, 0xD0, 0x00]
    + [0x07, 0x05, 0x03, 0x01, 0xE4, 0x00, 0x01]
    + [0x07, 0x05, 0x83, 0x01, 0x40, 0x00, 0x01]
)

KEYBOARD_CONFIG = bytes(
    [0x09, 0x02, 0x22, 0x00, 0x01, 0x01, 0x00, 0xA0, 0x32]
    + [0x09, 0x04, 0x00, 0x00, 0x01, 0x03, 0x01, 0x01, 0x00]
    + [0x09, 0x21, 0x11, 0x01, 0x00, 0x01, 0x22, 0x3F, 0x00]
    + [0x07, 0x05, 0x81, 0x03, 0x08, 0x00, 0x0A]
)


def x360_report(b2=0, b3=0, lt=0, rt=0, lx=0, ly=0, rx=0, ry=0):
    return bytes([0x00, 0x14, b2, b3, lt, rt]) + struct.pack("<hhhh", lx, ly, rx, ry) + bytes(6)


def gip_report(b4=0, b5=0, lt=0, rt=0, lx=0, ly=0, rx=0, ry=0, seq=1):
    return bytes([0x20, 0x00, seq, 0x0E, b4, b5]) + struct.pack(
        "<HHhhhh", lt, rt, lx, ly, rx, ry
    )


def test_finds_controller_interfaces_and_skips_everything_else():
    assert find_xbox_interface(X360_CONFIG) == (KIND_360, 0, 0x81, 0x01)
    assert find_xbox_interface(GIP_CONFIG) == (KIND_GIP, 0, 0x82, 0x02)
    assert find_xbox_interface(KEYBOARD_CONFIG) is None
    assert find_xbox_interface(b"") is None
    assert find_xbox_interface(X360_CONFIG[:20]) is None  # truncated


@pytest.mark.parametrize(
    "up, down, left, right, hat",
    [
        (0, 0, 0, 0, HAT_CENTERED),
        (1, 0, 0, 0, 0),
        (1, 0, 0, 1, 1),
        (0, 0, 0, 1, 2),
        (0, 1, 0, 1, 3),
        (0, 1, 0, 0, 4),
        (0, 1, 1, 0, 5),
        (0, 0, 1, 0, 6),
        (1, 0, 1, 0, 7),
        (1, 1, 0, 0, HAT_CENTERED),
    ],
)
def test_dpad_to_hat(up, down, left, right, hat):
    assert dpad_to_hat(up, down, left, right) == hat


def test_parse_360_report():
    state = PadState()
    data = x360_report(
        b2=0b10101001,  # up, right, back, right-stick click
        b3=0b10010101,  # LB, guide, A, Y
        lt=12, rt=255, lx=-100, ly=200, rx=-32768, ry=32767,
    )
    assert parse_360_report(data, state)
    assert state.buttons == BTN_A | BTN_Y | BTN_LB | BTN_VIEW | BTN_RS | BTN_GUIDE
    assert state.hat == 1
    assert (state.lt, state.rt) == (12, 255)
    assert (state.lx, state.ly, state.rx, state.ry) == (-100, 200, -32768, 32767)
    assert state.has_report


def test_parse_360_ignores_non_input_messages():
    state = PadState()
    assert not parse_360_report(bytes([0x01, 0x03, 0x06]), state)  # LED status
    assert not parse_360_report(bytes([0x08, 0x80]), state)
    assert not state.has_report


def test_parse_gip_input_and_guide():
    state = PadState()
    assert parse_gip_guide(bytes([0x07, 0x20, 0x05, 0x02, 0x01, 0x5B]), state)
    assert state.buttons == BTN_GUIDE
    data = gip_report(
        b4=0b00010100,  # menu, A
        b5=0b00000110,  # down, left
        lt=1023, rt=512, lx=1, ly=-2, rx=3000, ry=-4000,
    )
    assert parse_gip_input(data, state)
    assert state.buttons == BTN_A | BTN_MENU | BTN_GUIDE  # guide survives the input packet
    assert state.hat == 5
    assert (state.lt, state.rt) == (255, 128)
    assert (state.lx, state.ly, state.rx, state.ry) == (1, -2, 3000, -4000)
    assert parse_gip_guide(bytes([0x07, 0x20, 0x06, 0x02, 0x00, 0x5B]), state)
    assert state.buttons == BTN_A | BTN_MENU
    assert not parse_gip_input(bytes([0x03, 0x20, 0x00, 0x04]), state)  # heartbeat


def test_gip_init_packets_follow_xpad():
    generic = gip_init_packets(0x045E, 0x0B12)  # Xbox Series X|S
    assert generic[0] == bytes([0x05, 0x20, 0x00, 0x01, 0x00])
    assert [p[0] for p in generic] == [0x05, 0x0A, 0x06]
    one_s = gip_init_packets(0x045E, 0x02EA)
    assert bytes([0x05, 0x20, 0x00, 0x0F, 0x06]) in one_s
    hori = gip_init_packets(0x0F0D, 0x0067)
    assert hori[0][0] == 0x01 and hori[1][0] == 0x05


class FakeDevice:
    """Stands in for usb.core.Device."""

    def __init__(self, packets, vendor=0x045E, product=0x0B12, quiet_timeouts=True):
        self.packets = list(packets)
        self.written = []
        self.idVendor = vendor
        self.idProduct = product
        self.product = "Controller"
        self.configured = False
        self.quiet_timeouts = quiet_timeouts

    def is_kernel_driver_active(self, interface):
        return False

    def set_configuration(self):
        self.configured = True

    def write(self, endpoint, data, timeout=None):
        self.written.append((endpoint, bytes(data)))
        return len(data)

    def read(self, endpoint, buffer, timeout=None, **kwargs):
        if kwargs and not self.quiet_timeouts:
            raise TypeError("unexpected keyword argument")
        if not self.packets:
            if kwargs.get("raise_on_timeout") is False:
                return 0
            raise xbox_pad._USBTimeoutError()
        packet = self.packets.pop(0)
        buffer[: len(packet)] = type(buffer)("B", packet)
        return len(packet)


def test_gip_pad_starts_with_sequenced_init_packets():
    device = FakeDevice([])
    pad = XboxPad(device, KIND_GIP, 0, 0x82, 0x02)
    pad.start()
    assert device.configured
    assert [data[2] for _, data in device.written] == [0, 1, 2]
    assert all(endpoint == 0x02 for endpoint, _ in device.written)


def test_gip_pad_polls_input_and_acks_guide():
    device = FakeDevice(
        [bytes([0x07, 0x30, 0x09, 0x02, 0x01, 0x5B]), gip_report(rx=5000, ry=-6000)]
    )
    pad = XboxPad(device, KIND_GIP, 0, 0x82, 0x02)
    assert pad.poll()  # guide pressed, with the "please ack" flag
    ack_endpoint, ack = device.written[-1]
    assert ack_endpoint == 0x02 and ack[:3] == bytes([0x01, 0x20, 0x09])
    assert pad.poll()
    assert (pad.state.rx, pad.state.ry) == (5000, -6000)
    assert pad.state.buttons == BTN_GUIDE
    assert pad.poll() is False  # nothing new: a timeout is not an error


def test_older_circuitpython_timeouts_are_handled():
    device = FakeDevice([x360_report(rx=123)], quiet_timeouts=False)
    pad = XboxPad(device, KIND_360, 0, 0x81, 0x01)
    assert pad.poll() and pad.state.rx == 123
    assert pad.poll() is False


def test_announce_packet_triggers_init_again():
    device = FakeDevice([bytes([0x02, 0x20, 0x01, 0x1C] + [0] * 28)])
    pad = XboxPad(device, KIND_GIP, 0, 0x82, 0x02)
    assert pad.poll() is False
    assert [data[0] for _, data in device.written] == [0x05, 0x0A, 0x06]
