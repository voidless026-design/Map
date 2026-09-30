# Stick Drift Fix for the Adafruit Fruit Jam

A Fruit Jam OS app that sits between a wired Xbox controller and your PC and takes
the drift out of the right (aim) stick.

```
Xbox controller --USB--> Fruit Jam (USB-A host port) --USB-C--> PC
```

What it does:

- **Measures the stick at rest.** When the controller connects, or when you press
  Button 1, it records where the stick really rests and how much it wanders while
  nobody touches it. This takes 2 seconds with your thumbs off the sticks.
- **Re-centers the stick.** It subtracts that resting offset, so a stick that rests
  slightly up-right counts as centered.
- **Ignores the drift.** Any movement inside the measured drift plus a small margin
  is sent to the PC as "centered". Bigger movements pass straight through. They are
  rescaled so there is no jump at the edge of the deadzone, and full deflection still
  means full deflection.

It does nothing else to your aim: nothing is added, and nothing reacts to firing or
to what happens in the game. Buttons, triggers and the left stick pass through as-is.
To fix a drifting left stick as well, set `FIX_LEFT_STICK = True`.

## What you need

- An Adafruit Fruit Jam running CircuitPython 10 (Fruit Jam OS or plain CircuitPython).
- A **wired** Xbox controller: Xbox 360, Xbox One, Xbox Series X|S, Elite, or a
  third-party pad in XInput mode. Xbox One and Series controllers work over a USB
  data cable. The Xbox Wireless Adapter and Bluetooth are not supported.
- A USB-C data cable from the Fruit Jam to the PC.

## Install on Fruit Jam OS

1. Plug the Fruit Jam into the PC so the `CIRCUITPY` drive appears.
2. Copy `CIRCUITPY/apps/Stick_Drift_Fix` from this folder into `CIRCUITPY/apps/` on
   the drive.
3. Copy `CIRCUITPY/lib/stick_drift_gamepad.py` into `CIRCUITPY/lib/` on the drive.
4. Open `CIRCUITPY/boot.py` on the drive and add these two lines at the very top.
   Keep the rest of the file: it is the Fruit Jam OS launcher's.

   ```python
   import stick_drift_gamepad
   stick_drift_gamepad.enable()
   ```

   This adds a USB gamepad to the devices the Fruit Jam shows the PC, next to the
   usual CircuitPython keyboard, mouse and media keys. It has to go in `boot.py`
   because USB devices can only be set up before the PC sees the board.
5. Press the Fruit Jam's **reset** button, then pick **Stick Drift Fix** in the
   launcher.
6. Plug the Xbox controller into a USB-A port. Keep your thumbs off the sticks while
   the LEDs are blue.

To go back to the launcher, press reset.

## Install on plain CircuitPython (no Fruit Jam OS)

1. Copy `code.py`, `stick_filter.py` and `xbox_pad.py` from
   `CIRCUITPY/apps/Stick_Drift_Fix/` to the root of the `CIRCUITPY` drive.
2. Copy `CIRCUITPY/lib/stick_drift_gamepad.py` into `CIRCUITPY/lib/`.
3. Add the two `boot.py` lines above to `CIRCUITPY/boot.py`. Create the file if it
   doesn't exist.
4. For the status LEDs, install the NeoPixel library: `circup install neopixel`. The
   app works without it.
5. Press reset.

## On the PC

The Fruit Jam shows up as a standard USB gamepad, not as an Xbox controller.
CircuitPython can't pretend to be an Xbox controller. Games that only read Xbox
controllers, Apex Legends included, need Steam Input to translate:

1. In Steam, open **Settings → Controller** and turn on Steam Input for generic
   gamepads.
2. Map the pad once when Steam asks. The buttons are numbered A=1, B=2, X=3, Y=4,
   LB=5, RB=6, View=7, Menu=8, left-stick click=9, right-stick click=10 and Guide=11.
   The D-pad is the hat, the sticks are X/Y (left) and Rx/Ry (right), and the
   triggers are Z and Rz.
3. Launch Apex from Steam. If you play through the EA app, add Apex to Steam as a
   non-Steam game so Steam Input applies.
4. Turn Apex's own look deadzone and Steam's stick deadzone down to their smallest
   settings. The Fruit Jam already removes the drift, and a second deadzone on top
   makes small aim movements feel dead.

This does not work on consoles, because consoles only accept controllers they can
authenticate.

## About "2 pixels"

The Fruit Jam can't see your screen. It only sees stick numbers, from −32768 to 32767
per axis. How many pixels a given stick value moves the crosshair depends on your
sensitivity, FOV and resolution. Drift is also a speed, not a distance: a drifting
stick keeps creeping for as long as you leave it. So the app doesn't use a pixel
threshold. It measures your stick's actual drift and ignores everything up to that
amount plus a margin.

To tune it until the crosshair stays put when you let go:

1. In the Firing Range, let go of the right stick and watch the crosshair for
   10 seconds.
2. Flick the stick in each direction and let go each time. Worn sticks often come to
   rest at a slightly different spot depending on the direction they came from.
3. If the crosshair still creeps, open `CIRCUITPY/apps/Stick_Drift_Fix/code.py`,
   raise `MIN_DEADZONE` by `0.01`, save, and press reset. Repeat until it stops.
4. If it no longer creeps but tiny aim adjustments feel unresponsive, lower
   `MIN_DEADZONE` by `0.01` until they come back.

## Buttons and lights

| Fruit Jam | What it does |
|---|---|
| Button 1 | Re-calibrate (thumbs off both sticks for 2 seconds) |
| Button 2 | Drift fix on/off, to compare with and without it |
| Button 3 | Live monitor on/off: prints raw and sent right-stick values 4 times a second |

| LEDs | Meaning |
|---|---|
| Blue | Calibrating: don't touch the sticks |
| Green | Drift fix on |
| White | Drift fix off (raw passthrough) |
| Yellow | No controller plugged in |
| Red | Needs attention: read the message on the screen or serial console |

Messages appear on the Fruit Jam's HDMI screen and on the serial console. After
calibration it prints the stick's resting point, its drift and the deadzone it
chose, for example:

```
Right stick: rests at (+2940, -1880), drift 1.2%, deadzone 5.0%
```

## Settings (top of `code.py`)

| Setting | Default | Meaning |
|---|---|---|
| `FIX_RIGHT_STICK` | `True` | Fix the aim stick |
| `FIX_LEFT_STICK` | `False` | Fix the movement stick too |
| `MIN_DEADZONE` | `0.05` | Smallest deadzone, as a fraction of full travel (0.05 = 5%) |
| `DEADZONE_MARGIN` | `0.03` | Added on top of the drift measured during calibration |
| `MAX_DEADZONE` | `0.25` | Largest deadzone calibration may choose |
| `MAX_REST_NOISE` | `0.25` | More movement than this during calibration means the stick was touched, so the result is discarded |
| `CALIBRATION_MS` | `2000` | How long calibration listens |

## Files

```
CIRCUITPY/
  lib/stick_drift_gamepad.py          USB gamepad for the PC (boot.py enables it)
  apps/Stick_Drift_Fix/
    code.py                           the app: settings, buttons, LEDs, main loop
    stick_filter.py                   re-centering, deadzone, calibration (pure maths)
    xbox_pad.py                       wired Xbox 360 / One / Series driver for USB host
    metadata.json, icon.bmp           Fruit Jam OS launcher title and 64x64 icon
tests/                                desktop tests with simulated controllers
```

## Tests

The drift maths, the controller report parsing, the USB report layout and the app
loop are tested on a desktop with simulated controllers. Run them from the
repository root:

```bash
python3 -m pytest fruitjam/stick-drift-fix/tests
```

The code hasn't been run on a physical Fruit Jam yet. The Xbox report layouts and
start-up packets follow the Linux `xpad` driver. If your controller connects but
nothing moves, turn on the live monitor (Button 3) and check the screen for errors.
