# SPDX-License-Identifier: MIT
"""Stick Drift Fix for the Adafruit Fruit Jam.

Plug a wired Xbox controller into one of the Fruit Jam's USB-A ports and the Fruit
Jam's USB-C port into the PC. The Fruit Jam passes the controller through as a USB
gamepad, with the drift taken out of the right (aim) stick:

  * the stick's real resting point is measured while you're not touching it, and
  * any small movement around that point (the drift) is sent to the PC as "centered".

Every movement bigger than the drift is passed through as-is (rescaled so there is no
jump at the edge of the deadzone). Nothing is added to or taken away from your aim.

Fruit Jam buttons:
  Button 1  re-calibrate (take your thumbs off both sticks for 2 seconds)
  Button 2  drift fix on/off, to compare with and without it
  Button 3  live monitor on/off (prints raw and corrected stick values)

NeoPixels: blue = calibrating, green = fix on, white = fix off,
yellow = no controller, red = something needs attention (see the screen).

Needs one-time setup in boot.py; see README.md.
"""

import time

import board
import stick_drift_gamepad
import usb_hid
from stick_filter import Calibrator, StickFilter, deadzone_for
from xbox_pad import find_pad

# --- Configuration -------------------------------------------------------------------
# Stick values are fractions of full travel: 0.05 means 5% of the way to the edge.

FIX_RIGHT_STICK = True  # the aim stick
FIX_LEFT_STICK = False  # set True if your movement stick drifts too

# Smallest deadzone ever used. If the crosshair still creeps when you let go of the
# stick, raise this by 0.01 at a time until it stops.
MIN_DEADZONE = 0.05
# Room added on top of the drift measured during calibration.
DEADZONE_MARGIN = 0.03
# Largest deadzone calibration may pick. A bigger one would eat small aim movements.
MAX_DEADZONE = 0.25
# A stick that wanders more than this at rest is being touched: calibration is retried.
MAX_REST_NOISE = 0.25

CALIBRATION_MS = 2000
READ_TIMEOUT_MS = 8  # how long one read waits for the controller
MONITOR_INTERVAL_MS = 250  # time between live monitor lines
LED_BRIGHTNESS = 0.05

# --- Status LEDs and buttons -----------------------------------------------------------

BLUE = (0, 0, 255)
GREEN = (0, 255, 0)
WHITE = (255, 255, 255)
YELLOW = (255, 160, 0)
RED = (255, 0, 0)


class Leds:
    def __init__(self):
        self.pixels = None
        self.color = None
        try:
            import neopixel

            self.pixels = neopixel.NeoPixel(
                board.NEOPIXEL, 5, brightness=LED_BRIGHTNESS, auto_write=True
            )
        except Exception:
            pass  # LEDs are optional (the neopixel library may not be installed)

    def show(self, color):
        if self.pixels is not None and color != self.color:
            self.pixels.fill(color)
            self.color = color


def now_ms():
    # Integer milliseconds: time.monotonic() loses precision after long uptimes.
    return time.monotonic_ns() // 1000000


def make_buttons():
    try:
        import keypad

        return keypad.Keys(
            (board.BUTTON1, board.BUTTON2, board.BUTTON3), value_when_pressed=False, pull=True
        )
    except Exception:
        return None


def pressed_buttons(keys):
    """Return the numbers (1-3) of Fruit Jam buttons pressed since the last call."""
    presses = []
    if keys is None:
        return presses
    event = keys.events.get()
    while event is not None:
        if event.pressed:
            presses.append(event.key_number + 1)
        event = keys.events.get()
    return presses


# --- Main loop -------------------------------------------------------------------------


class DriftFix:
    def __init__(self, output):
        self.output = output
        self.leds = Leds()
        self.keys = make_buttons()
        self.pad = None
        self.enabled = True
        self.monitor = False
        self.next_monitor = 0
        self.left = StickFilter(deadzone_for(None, MIN_DEADZONE, DEADZONE_MARGIN, MAX_DEADZONE))
        self.right = StickFilter(deadzone_for(None, MIN_DEADZONE, DEADZONE_MARGIN, MAX_DEADZONE))
        self.calibrating = None  # (left Calibrator, right Calibrator, end time)
        self.last_report = None

    def send(self, report):
        if report != self.last_report:
            try:
                self.output.send_report(report)
                self.last_report = report
            except OSError:
                pass  # PC not listening (asleep or unplugged); try again next change

    def start_calibration(self):
        print("Calibrating: take your thumbs off both sticks for %.1f seconds..."
              % (CALIBRATION_MS / 1000))
        self.calibrating = (
            Calibrator(MAX_REST_NOISE),
            Calibrator(MAX_REST_NOISE),
            now_ms() + CALIBRATION_MS,
        )

    def finish_calibration(self):
        left_cal, right_cal, _ = self.calibrating
        self.calibrating = None
        if left_cal.count == 0:
            print("No input from the controller yet. Move a stick once, then press Button 1.")
            return False
        results = (
            ("Left", self.left, left_cal.result()),
            ("Right", self.right, right_cal.result()),
        )
        if any(result is None for _, _, result in results):
            print("A stick moved during calibration. Hands off the sticks, then press Button 1.")
            print("Keeping the previous settings for now.")
            return False
        for name, stick, result in results:
            stick.center_x = result.center_x
            stick.center_y = result.center_y
            stick.deadzone = deadzone_for(result, MIN_DEADZONE, DEADZONE_MARGIN, MAX_DEADZONE)
            print("%s stick: rests at (%+d, %+d), drift %.1f%%, deadzone %.1f%%" % (
                name, result.center_x, result.center_y, result.noise * 100, stick.deadzone * 100))
            if result.noise + DEADZONE_MARGIN > MAX_DEADZONE:
                print("  This stick drifts more than MAX_DEADZONE allows; it may still creep.")
        return True

    def connect(self):
        try:
            self.pad = find_pad(READ_TIMEOUT_MS)
        except Exception as error:  # a controller that failed to start
            print("Controller did not start:", error)
            self.pad = None
        if self.pad is not None:
            print("Connected:", self.pad.name, "(%s protocol)" % self.pad.kind)
            self.start_calibration()

    def disconnect(self):
        print("Controller unplugged. Plug it back in to continue.")
        self.pad = None
        self.calibrating = None
        self.send(stick_drift_gamepad.NEUTRAL_REPORT)  # never leave a stick held on the PC

    def handle_buttons(self):
        for number in pressed_buttons(self.keys):
            if number == 1 and self.pad is not None:
                self.start_calibration()
            elif number == 2:
                self.enabled = not self.enabled
                print("Drift fix", "ON" if self.enabled else "OFF (raw passthrough)")
            elif number == 3:
                self.monitor = not self.monitor
                print("Live monitor", "ON" if self.monitor else "OFF")

    def corrected(self, state):
        lx, ly, rx, ry = state.lx, state.ly, state.rx, state.ry
        if self.calibrating is not None:
            return 0, 0, 0, 0  # hold the sticks still on the PC while measuring
        if self.enabled and FIX_LEFT_STICK:
            lx, ly = self.left.apply(lx, ly)
        if self.enabled and FIX_RIGHT_STICK:
            rx, ry = self.right.apply(rx, ry)
        return lx, ly, rx, ry

    def print_monitor(self, state, rx, ry):
        now = now_ms()
        if not self.monitor or now < self.next_monitor:
            return
        self.next_monitor = now + MONITOR_INTERVAL_MS
        full = 32767
        print("R raw %+.3f %+.3f -> sent %+.3f %+.3f  (deadzone %.3f)" % (
            state.rx / full, state.ry / full, rx / full, ry / full, self.right.deadzone))

    def update_leds(self):
        if self.pad is None:
            self.leds.show(YELLOW)
        elif self.calibrating is not None:
            self.leds.show(BLUE)
        else:
            self.leds.show(GREEN if self.enabled else WHITE)

    def step(self):
        self.handle_buttons()
        if self.pad is None:
            self.update_leds()
            self.connect()
            if self.pad is None:
                time.sleep(0.5)
            return

        try:
            self.pad.poll()
        except Exception as error:  # usually usb.core.USBError: the controller went away
            print("Controller read failed:", repr(error))
            self.disconnect()
            return

        state = self.pad.state
        if self.calibrating is not None:
            left_cal, right_cal, end = self.calibrating
            if state.has_report:  # sample the current state every loop, new report or not
                left_cal.add(state.lx, state.ly)
                right_cal.add(state.rx, state.ry)
            if now_ms() >= end:
                if not self.finish_calibration():
                    self.leds.show(RED)
                    time.sleep(1.0)

        lx, ly, rx, ry = self.corrected(state)
        self.send(stick_drift_gamepad.pack_report(
            state.buttons, state.hat, lx, ly, rx, ry, state.lt, state.rt))
        self.print_monitor(state, rx, ry)
        self.update_leds()


def main():
    output = stick_drift_gamepad.find_device(usb_hid.devices)
    if output is None:
        print("The USB gamepad is not enabled. Add these two lines to CIRCUITPY/boot.py,")
        print("then press the Fruit Jam's reset button:")
        print("    import stick_drift_gamepad")
        print("    stick_drift_gamepad.enable()")
        Leds().show(RED)
        while True:
            time.sleep(1)

    print("Stick Drift Fix ready. Plug a wired Xbox controller into a USB-A port.")
    app = DriftFix(output)
    while True:
        app.step()


if __name__ == "__main__":  # CircuitPython runs code.py as __main__
    main()
