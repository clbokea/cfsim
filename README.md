# cfsim – a lightweight Crazyflie simulator for the classroom

cfsim lets students run their normal **cflib** Python scripts on a simulated
Crazyflie, with a live 3D view, on Windows, macOS and Linux. No Docker, no
Linux virtual machine, no graphics card needed.

The same script flies the simulator and the real drone:

```
python -m cfsim my_script.py      # simulator
python my_script.py               # real Crazyflie (needs a Crazyradio)
```

## Installation

You need Python 3.8 or newer.

```
pip install ./cfsim               # from the folder containing pyproject.toml
pip install cflib                 # only needed to fly the real drones
```

(Or from a zip file: `pip install cfsim-1.0.2.zip`.)

Check that it works:

```
python -m cfsim --list-worlds
python -m cfsim examples/01_hello_fly.py
```

A window opens showing the drone in 3D and from above. The window stays open
after the script ends so you can look at the flight path; close it when done.

## Two ways to use the simulator

**1. From the command line (recommended)** – the script is not changed at all:

```
python -m cfsim my_script.py
python -m cfsim --world maze --model brushless my_script.py
```

**2. From an editor's "Run" button** (VS Code, Thonny, PyCharm) – add two lines
at the very top of the script, *before* any `cflib` import:

```python
import cfsim
cfsim.enable()          # delete or comment out this line to fly the real drone

import cflib.crtp
...
```

`cfsim.enable()` accepts the same options as the command line, for example
`cfsim.enable(world='obstacles', model='brushless')`.

## Using cfsim in a Jupyter notebook

Put `cfsim.enable()` in the first cell, before any cflib import. Flying works
the same as in a script; the cell runs until the flight is finished.

```python
import cfsim
cfsim.enable(world='obstacles')          # first cell
```

- On your own computer (Jupyter or VS Code notebooks) the live 3D view opens
  as a separate window, as with scripts.
- `cfsim.show()` draws the world and the flight paths **inside the notebook**,
  below the cell. This also works in online notebooks (JupyterHub, Google
  Colab) where no separate window can open – use `cfsim.enable(viewer=False)`
  there.
- `cfsim.reset()` puts all drones back at their start spots, so you can re-run
  a flight cell.
- To change the world or other options, restart the kernel.

See `examples/notebook_demo.ipynb`.

## Options

| Command line | `enable()` | Meaning |
| --- | --- | --- |
| `--world NAME` | `world='room'` | `room`, `corridor`, `maze`, `obstacles`, `arena`, `open`, or a path to your own map |
| `--model M` | `model='2.1+'` | `2.1+` or `brushless` |
| | `models={uri: 'brushless'}` | mix models in one swarm |
| `--positioning P` | `positioning='flow'` | `flow` (Flow deck), `lighthouse` (absolute) or `none` |
| `--no-noise` | `noise=False` | perfect sensors, no drift |
| `--decks flow,multiranger` | `decks=('flow', 'multiranger')` | which decks are mounted |
| `--battery-drain 10` | `battery_drain=10` | battery empties 10× faster |
| `--no-viewer` | `viewer=False` | no window (faster, for testing) |
| | `start_positions={uri: (x, y)}` | place drones yourself |
| | `quiet=True` | hide simulator messages |

Every URI is a separate simulated drone, so you can keep the real radio
addresses in your scripts.

## What the simulator does (and why it matters on the real drone)

cfsim simulates the parts that students run into when programming real
Crazyflies:

- **Same commands**: `MotionCommander`, `PositionHlCommander`, the low-level
  `commander` setpoints, the `high_level_commander`, `Multiranger`, logging
  (`LogConfig`, `SyncLogger`), parameters, `Swarm`, and the supervisor.
- **Flow deck positioning**: positions are measured from the take-off spot
  and drift slowly, like on the real drone. Use `--positioning lighthouse` for
  an absolute, accurate position system.
- **Sensors**: Multi-ranger distances (front, back, left, right, up) and the
  Flow deck height, in millimetres, with noise and a 4 m maximum range.
  Values of 8000 or more mean "nothing in range" (cflib's `Multiranger`
  turns them into `None`).
- **Commander watchdog**: low-level setpoints must be sent continuously. After
  0.5 s without one the drone stops moving; after 2 s the motors stop and it
  falls (see `examples/06_low_level_setpoints.py`).
- **Thrust lock**: `send_setpoint()` needs one setpoint with thrust 0 first.
- **Arming**: the Brushless model ignores flight commands until
  `cf.supervisor.send_arming_request(True)` is sent.
- **Crashes**: into walls, the ceiling, other drones, or by falling too hard.
  A crashed drone stops responding (`send_crash_recovery_request()` resets it
  once it is on the ground).
- **Log limits**: a log configuration can hold at most 26 bytes, and only
  variables that exist on the drone (with its decks) can be logged.
- **Battery**: drains during flight (`pm.vbat`, `pm.batteryLevel`).
- **Radio signal strength** (`radio.rssi`) to the home beacon, for
  return-home and SGBA-style exercises.

### Simplifications

The physics is simple on purpose: the drone follows velocity commands with a
short delay instead of simulating propellers and attitude control. That is
enough for learning to program flight behaviour, sensing and swarms, but not
for tuning controllers. Raw thrust values (`send_setpoint`) only roughly
match the real drones. Cameras (AI deck), uploaded trajectories, memory
access and the Loco/Lighthouse hardware itself are not simulated.

Always test new scripts carefully on the real drone too: the simulator is a
first check, not a guarantee.

## Log variables available

`stateEstimate.x/y/z/vx/vy/vz/roll/pitch/yaw`, `kalman.stateX/Y/Z`,
`stabilizer.roll/pitch/yaw/thrust`, `acc.x/y/z`, `gyro.x/y/z`,
`range.front/back/left/right/up` (Multi-ranger), `range.zrange` (Flow deck),
`pm.vbat`, `pm.batteryLevel`, `pm.state`, `radio.rssi`, `supervisor.info`.

## Worlds

| World | Description |
| --- | --- |
| `room` | 5 × 5 m room (default) |
| `corridor` | L-shaped corridor, 1 m wide – wall following |
| `maze` | small maze with 1 m corridors |
| `obstacles` | 6 × 6 m room with four pillars |
| `arena` | 7 × 7 m empty arena with start spots for 8 drones |
| `open` | no walls, no ceiling |

### Make your own world

A world is a text file. Each character is a 0.5 m square:

```
; my_world.txt - lines starting with ';' are comments
height: 2.5
##########
#S.......#
#....##..#
#....##..#
#1.2.....#
##########
```

`#` is a wall, `S` the start (and home beacon), `1`–`9` extra start spots for
swarms, `B` a separate beacon position, `.` or space is free. The start `S`
is position (0, 0); x points right and y points up on the map, and the drone
starts facing +x (to the right). Run it with `--world my_world.txt`.

## Examples

| File | Shows |
| --- | --- |
| `01_hello_fly.py` | take off, fly a square, land (`MotionCommander`) |
| `02_read_sensors.py` | logging position and Multi-ranger distances |
| `03_avoid_walls.py` | exploring a room without crashing (`Multiranger`) |
| `04_go_to_points.py` | flying to coordinates (`PositionHlCommander`) |
| `05_swarm.py` | three drones at once (`Swarm`); try `--world arena` |
| `06_low_level_setpoints.py` | continuous setpoints and the watchdog |

## Troubleshooting

- **No window appears**: first look behind your other windows, or for a
  Python icon in the Dock/taskbar. Then run `python -m cfsim.viewer --check`:
  it opens a test window, or prints why it can't (no screen, e.g. over SSH or
  in a container; or no window toolkit – on macOS with Homebrew Python run
  `brew install python-tk`, on Linux `sudo apt install python3-tk`). The
  simulation also runs without the window.
- **"cflib was imported before cfsim.enable()"**: move `import cfsim` and
  `cfsim.enable()` to the very top of the script.
- **"... is not available in the cfsim simulator"**: the script uses a part of
  cflib that cfsim does not simulate.
- **The drone does nothing**: read the `[cfsim]` messages in the terminal –
  they explain why (not armed, thrust lock, crashed, battery empty, ...).
