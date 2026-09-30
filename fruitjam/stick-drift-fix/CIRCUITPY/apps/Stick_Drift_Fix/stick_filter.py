# SPDX-License-Identifier: MIT
"""Stick drift correction: re-centering plus a scaled radial deadzone.

Pure Python with no hardware imports, so it runs (and is tested) on a desktop too.

Stick values are the raw Xbox numbers: -32768..32767 per axis, up and right positive.
Deadzones and noise are fractions of full travel (0.05 = 5% of the way to the edge).
"""

import math

FULL_SCALE = 32767


def _clamp(value, low, high):
    return low if value < low else high if value > high else value


def _normalize(value, center):
    """Map a raw axis value to -1.0..1.0 around a (possibly off-center) rest point.

    Each side is scaled on its own, so a stick that rests at +2000 still reaches
    full deflection in both directions.
    """
    delta = value - center
    span = FULL_SCALE - center if delta > 0 else FULL_SCALE + center
    if span <= 0:
        return 0.0
    return _clamp(delta / span, -1.0, 1.0)


class StickFilter:
    """Removes drift from one analog stick.

    1. Subtracts the stick's measured rest position (its center offset).
    2. Treats anything inside the deadzone circle as "centered" (drift).
    3. Rescales the rest of the travel so output ramps up from 0 at the deadzone edge
       (no jump) and still reaches full deflection at the edge of the stick.
    """

    def __init__(self, deadzone=0.08, center_x=0, center_y=0):
        self.deadzone = deadzone
        self.center_x = center_x
        self.center_y = center_y

    def apply(self, x, y):
        nx = _normalize(x, self.center_x)
        ny = _normalize(y, self.center_y)
        magnitude = math.sqrt(nx * nx + ny * ny)
        if magnitude <= self.deadzone:
            return 0, 0
        scale = (magnitude - self.deadzone) / (1.0 - self.deadzone) / magnitude
        out_x = _clamp(nx * scale, -1.0, 1.0)
        out_y = _clamp(ny * scale, -1.0, 1.0)
        return round(out_x * FULL_SCALE), round(out_y * FULL_SCALE)


class Calibration:
    """What one stick does when nobody is touching it."""

    def __init__(self, center_x, center_y, noise):
        self.center_x = center_x
        self.center_y = center_y
        self.noise = noise  # how far it wanders from center at rest, 0.0..1.0


class Calibrator:
    """Collects resting samples for one stick and works out its center and noise.

    Keeps only running sums and a bounding box, so memory use is constant however
    long it runs. The noise is measured to the far corner of the box, which errs on
    the side of a slightly bigger deadzone.
    """

    def __init__(self, max_rest_noise=0.25):
        self.max_rest_noise = max_rest_noise
        self.count = 0
        self._sum_x = 0
        self._sum_y = 0
        self._min_x = self._min_y = FULL_SCALE + 1
        self._max_x = self._max_y = -FULL_SCALE - 2

    def add(self, x, y):
        self.count += 1
        self._sum_x += x
        self._sum_y += y
        self._min_x = min(self._min_x, x)
        self._max_x = max(self._max_x, x)
        self._min_y = min(self._min_y, y)
        self._max_y = max(self._max_y, y)

    def result(self):
        """Return a Calibration, or None if there were no samples or the stick moved.

        A noise above ``max_rest_noise`` means someone was holding the stick, so the
        measurement is thrown away rather than turned into a huge deadzone.
        """
        if self.count == 0:
            return None
        center_x = round(self._sum_x / self.count)
        center_y = round(self._sum_y / self.count)
        reach_x = max(center_x - self._min_x, self._max_x - center_x) / FULL_SCALE
        reach_y = max(center_y - self._min_y, self._max_y - center_y) / FULL_SCALE
        noise = math.sqrt(reach_x * reach_x + reach_y * reach_y)
        if noise > self.max_rest_noise:
            return None
        return Calibration(center_x, center_y, noise)


def deadzone_for(calibration, minimum, margin, maximum):
    """Deadzone that covers the measured drift plus a safety margin."""
    noise = calibration.noise if calibration is not None else 0.0
    return _clamp(max(minimum, noise + margin), 0.0, maximum)
