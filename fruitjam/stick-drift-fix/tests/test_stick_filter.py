import math

from stick_filter import FULL_SCALE, Calibration, Calibrator, StickFilter, deadzone_for


def test_drift_inside_deadzone_is_sent_as_centered():
    stick = StickFilter(deadzone=0.08)
    for x, y in ((0, 0), (1500, -900), (-2000, 1200), (2500, 0)):
        assert stick.apply(x, y) == (0, 0)


def test_off_center_rest_point_is_removed():
    # A worn stick that rests at (+3000, -2500) and jitters around it.
    stick = StickFilter(deadzone=0.05, center_x=3000, center_y=-2500)
    for dx, dy in ((0, 0), (400, -300), (-500, 250)):
        assert stick.apply(3000 + dx, -2500 + dy) == (0, 0)


def test_full_deflection_still_reached_with_offset_center():
    stick = StickFilter(deadzone=0.05, center_x=3000, center_y=-2500)
    assert stick.apply(32767, -2500) == (FULL_SCALE, 0)
    assert stick.apply(-32768, -2500) == (-FULL_SCALE, 0)
    assert stick.apply(3000, 32767) == (0, FULL_SCALE)
    assert stick.apply(3000, -32768) == (0, -FULL_SCALE)


def test_no_jump_at_deadzone_edge():
    stick = StickFilter(deadzone=0.10)
    just_outside = round(0.101 * FULL_SCALE)
    x, y = stick.apply(just_outside, 0)
    assert 0 < x < 0.01 * FULL_SCALE and y == 0


def test_output_grows_steadily_and_keeps_direction():
    stick = StickFilter(deadzone=0.08)
    previous = 0
    for step in range(9, 101):
        value = round(step / 100 * FULL_SCALE)
        x, y = stick.apply(value, value)  # diagonal up-right
        assert x == y and x >= previous
        previous = x
    x, y = stick.apply(-20000, 10000)
    assert x < 0 < y
    assert math.isclose(x / y, -2.0, rel_tol=0.01)


def test_calibrator_measures_center_and_noise():
    cal = Calibrator()
    for dx, dy in ((0, 0), (300, -200), (-300, 200), (150, 100), (-150, -100)):
        cal.add(2000 + dx, -1000 + dy)
    result = cal.result()
    assert (result.center_x, result.center_y) == (2000, -1000)
    expected = math.sqrt((300 / FULL_SCALE) ** 2 + (200 / FULL_SCALE) ** 2)
    assert math.isclose(result.noise, expected, rel_tol=1e-6)


def test_calibrator_rejects_a_touched_stick_and_empty_runs():
    cal = Calibrator(max_rest_noise=0.25)
    cal.add(0, 0)
    cal.add(20000, 0)  # someone pushed the stick
    assert cal.result() is None
    assert Calibrator().result() is None


def test_deadzone_covers_drift_plus_margin_within_limits():
    assert deadzone_for(None, 0.05, 0.03, 0.25) == 0.05
    assert math.isclose(deadzone_for(Calibration(0, 0, 0.01), 0.05, 0.03, 0.25), 0.05)
    assert math.isclose(deadzone_for(Calibration(0, 0, 0.07), 0.05, 0.03, 0.25), 0.10)
    assert deadzone_for(Calibration(0, 0, 0.40), 0.05, 0.03, 0.25) == 0.25


def test_calibrated_filter_silences_the_recorded_drift():
    samples = [(2400 + (i % 7) * 90, -1800 + (i % 5) * 110) for i in range(200)]
    cal = Calibrator()
    for x, y in samples:
        cal.add(x, y)
    result = cal.result()
    stick = StickFilter(deadzone_for(result, 0.05, 0.03, 0.25), result.center_x, result.center_y)
    assert all(stick.apply(x, y) == (0, 0) for x, y in samples)
    assert stick.apply(32767, -1800)[0] == FULL_SCALE
