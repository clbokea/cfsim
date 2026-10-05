# Running scripts in the simulator

This guide is for students and teachers who write cflib scripts and want to
run them in cfsim. For how cfsim works inside, see the
[developer guide](developer-guide.md).

## The one rule: simulator or real drone?

A cflib script does not know whether it flies a simulated or a real
Crazyflie. *How you start it* decides:

| Command | Flies |
| --- | --- |
| `python -m cfsim my_script.py` | the **simulator** |
| `python my_script.py` | the **real Crazyflie** (needs the real `cflib` and a Crazyradio) |

If you start a script with plain `python` and the real cflib is not installed,
you get:

```
ModuleNotFoundError: No module named 'cflib'
```

That means "you asked for the real drone". Use `python -m cfsim ...` instead.

## 1. Set up once

You need Python 3.8 or newer. We recommend [uv](https://docs.astral.sh/uv/),
because it creates the virtual environment for you.

**With uv** (one folder for your scripts):

```
uv init drone-course
cd drone-course
uv add "cfsim @ https://github.com/clbokea/cfsim/releases/download/v1.0.4/cfsim-1.0.4.zip"
```

Then put `uv run` in front of every command in this guide, for example
`uv run python -m cfsim my_script.py`.

**With a normal virtual environment:**

```
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install https://github.com/clbokea/cfsim/releases/download/v1.0.4/cfsim-1.0.4.zip
```

**In a clone of this repository** (to try the examples):

```
git clone https://github.com/clbokea/cfsim.git
cd cfsim
uv sync                            # creates .venv with cfsim and Jupyter
source .venv/bin/activate          # or use "uv run" in front of commands
```

Check that it works:

```
python -m cfsim --list-worlds
```

## 2. Run a script from the command line (recommended)

```
python -m cfsim my_script.py
```

The script is not changed at all. A window opens with a 3D view and a map seen
from above. It may open *behind* your other windows. It stays open after the
script ends so you can look at the flight path; close it when you are done.

Options go **before** the script name. Anything after the script name is
passed to your script.

```
python -m cfsim --world maze my_script.py
python -m cfsim --world obstacles --model brushless my_script.py
python -m cfsim --no-noise my_script.py
python -m cfsim --help
```

| Option | Meaning |
| --- | --- |
| `--world NAME` | `room` (default), `corridor`, `maze`, `obstacles`, `arena`, `open`, or a path to your own `.txt` map |
| `--model M` | `2.1+` (default) or `brushless` |
| `--positioning P` | `flow` (default: relative to the take-off spot, drifts), `lighthouse` (absolute) or `none` |
| `--no-noise` | perfect sensors and no drift – good for checking your logic |
| `--decks flow,multiranger` | which decks are mounted (default: both) |
| `--battery-drain 10` | the battery runs out 10× faster |
| `--viewer browser` | show the simulation in the web browser instead of a window |
| `--no-viewer` | no live view (faster; for testing) |
| `--list-worlds` | show the built-in worlds |

### The examples

From the repository folder:

```
python -m cfsim examples/01_hello_fly.py
python -m cfsim examples/02_read_sensors.py
python -m cfsim --world obstacles examples/03_avoid_walls.py
python -m cfsim examples/04_go_to_points.py
python -m cfsim --world arena examples/05_swarm.py
python -m cfsim examples/06_low_level_setpoints.py
```

The first lines of each example say what it shows and how to run it.

### The 3D view in the browser

```
python -m cfsim --viewer browser my_script.py
```

Instead of a window, the simulation opens in your web browser: the room in 3D
or from the top, the drone with its trail, the Multi-ranger rays, and battery
and status of every drone. The buttons at the top switch between **3D**,
**Top** and **Follow** (the camera follows the first drone) and show or hide
trails, sensor rays, the floor plan and the walls.

Leave the page open while you work: the next run of a script updates it
instead of opening a new tab. If the browser does not open by itself, open the
address the terminal prints (`http://127.0.0.1:8765/`).

## 3. Run a script with the editor's Run button

VS Code, Thonny and PyCharm run scripts with plain `python`, which means "real
drone". To use the simulator, add two lines at the **very top** of the script,
before any `cflib` import:

```python
import cfsim
cfsim.enable(world='obstacles')     # delete this line to fly the real drone

import cflib.crtp
...
```

`cfsim.enable()` takes the same options as the command line:

```python
cfsim.enable(world='maze', model='brushless', noise=False, viewer=True,
             positioning='lighthouse', battery_drain=10)
```

and a few that only exist here:

```python
cfsim.enable(models={'radio://0/80/2M/E7E7E7E702': 'brushless'})   # mixed swarm
cfsim.enable(start_positions={'radio://0/80/2M/E7E7E7E701': (1.0, 0.5)})
cfsim.enable(quiet=True)          # no [cfsim] messages
```

In VS Code, make sure the interpreter is the virtual environment where cfsim is
installed (*Python: Select Interpreter* → `.venv`).

If you get `cflib was imported before cfsim.enable()`, move the two cfsim
lines above all other imports that use cflib.

## 4. Run a Jupyter notebook

Put `import cfsim` and `cfsim.enable(...)` in the **first cell** and always run
the cells from the top.

```
uv run jupyter lab examples/notebook_demo.ipynb        # in a clone of this repo
```

In your own uv project, first add Jupyter: `uv add --dev jupyterlab`.

What you see in a notebook:

- **Live picture**: while a flight cell runs, a picture below the cell follows
  the drones. Switch it off with `cfsim.enable(inline=False)`.
- **3D window**: on your own computer the separate 3D window opens as well.
  In online notebooks (Colab, JupyterHub) use `cfsim.enable(viewer=False)`.
- `cfsim.replay()` plays the flight back as an animation with play/pause
  buttons. `cfsim.replay(speed=2)` is twice as fast.
- `cfsim.show()` draws a still picture of the flight paths.
- `cfsim.reset()` puts the drones back at their start spots so you can run a
  flight cell again.
- To change the world or another option, restart the kernel
  (*Kernel → Restart*) – `enable()` is ignored once the simulator is running.

In Google Colab, install in the first cell:

```
!pip install https://github.com/clbokea/cfsim/releases/download/v1.0.4/cfsim-1.0.4.zip
```

## 5. Several drones

Every URI is its own simulated drone, so keep the real radio addresses in your
scripts. Drones are placed on the start spots of the world (`S`, then `1`–`9`)
in the order they connect. The `arena` world has eight start spots:

```
python -m cfsim --world arena examples/05_swarm.py
```

Drones that touch each other crash, just like real ones.

## 6. Moving to the real drone

1. Test in the simulator with noise on (the default), not only with
   `--no-noise`.
2. Install the real library: `uv add cflib` (or `pip install cflib`).
3. Remove `cfsim.enable()` from the script if you added it, and run
   `python my_script.py`.
4. Fly carefully the first time. The simulator is a first check, not a
   guarantee – see *Simplifications* in the [README](https://github.com/clbokea/cfsim#readme).

Things that often differ on the real drone:

- **Positions** with the Flow deck start at (0, 0) where the drone took off
  and drift slowly – the same as in cfsim with `positioning='flow'`.
- **Brushless** drones must be armed:
  `scf.cf.supervisor.send_arming_request(True)`. Doing it on a 2.1+ is harmless,
  so keep it in all scripts.
- **Low-level setpoints** must be sent continuously (at least every 0.5 s),
  and `send_setpoint()` needs one setpoint with thrust 0 first.

## 7. Your own world

A world is a text file where each character is a 0.5 m square:

```
; my_world.txt
height: 2.5
##########
#S.......#
#....##..#
#1.2.....#
##########
```

`#` wall, `S` start and radio beacon (position 0, 0), `1`–`9` extra start
spots, `B` a separate beacon, `.` free. Run it with
`python -m cfsim --world my_world.txt my_script.py`.

### A room from a floor plan

To fly in a real building – your classroom, the lab, the hall – make the world
from an architectural drawing with the **room editor**:

```
python -m cfsim --editor
```

It opens in the browser and saves into the folder you started it from.

1. **Open the floor plan** – choose a PNG or JPG image of the plan. (A PDF must
   be exported as an image first, e.g. with *Export* in Preview or a
   screenshot.) *Try the example plan* loads a small demo building.
   The editor finds the building by itself (the blue box) and marks its walls
   in red. Text, door swings, furniture and dimension lines are thin, so they
   are removed automatically.
2. **How wide is the building?** – type the overall width from the
   measurements on the plan (the dimension along the whole building, outside
   wall to outside wall), choose its unit (m, cm or mm – plans often use cm
   or mm) and press Enter. The editor then shows the size of the building in
   metres – check the depth against the plan too.
3. **Where does the drone start?** – click on the plan where the drone takes
   off.
4. **Save** – give it a name and click **Save in the folder**. You get
   `name.txt` (the world) and `name.png` (the plan). Keep both in the same
   folder.

Then fly in it:

```
python -m cfsim --viewer browser --world name.txt my_script.py
```

The floor plan is drawn on the floor under the walls, so you can check that
the walls are in the right places. The world also works in the normal window
and in notebooks (`cfsim.enable(world='name.txt')`).

**Fine-tune** (only if the walls are not right):

| Problem | What to do |
| --- | --- |
| The blue box is not the building | *Area*: **Select area** and drag your own box, then type the width of that box. |
| You know another length, not the width | *Scale from another measurement*: **Measure**, click both ends, type the length. |
| A wall has gaps or is missing | **Paint wall**, or lower *Cell is wall if*. |
| Something that is not a wall is red | **Erase** it, or choose a stronger *Clean-up*. |
| Thin walls disappear | Choose *Clean-up: off*, or lower *Dark below* if the walls are grey. |
| The size is far too big or small | Check the unit next to the width (m, cm or mm). |
| Walls are drawn as two thin lines (not filled) | Usually fine: both lines become walls. If there are gaps, lower *Cell is wall if* or paint them. |
| A door should be open | **Erase** the wall across the doorway – the drone can only fly through free cells. |
| More drones | **Add start 1–9**. |

Tips:

- Both styles work: walls filled black or grey (the usual 1:100 or 1:50
  architectural style) and walls drawn as one dark line. For thin walls the
  editor uses 5 cm cells automatically.
- Doors drawn closed (a line across the opening) stay closed only if the line
  is thick; thin door lines are removed by the clean-up, so doors are open.

## 8. When something does not work

| Problem | What to do |
| --- | --- |
| `No module named 'cflib'` | You started the real-drone way. Use `python -m cfsim my_script.py`. |
| `No module named 'cfsim'` | cfsim is not installed in this Python. Activate the virtual environment, or use `uv run`. |
| `cflib was imported before cfsim.enable()` | Move `import cfsim` / `cfsim.enable()` to the very top. |
| `... is not available in the cfsim simulator` | The script uses a part of cflib that cfsim does not simulate. |
| The browser view does not open | Open the address printed in the terminal (`http://127.0.0.1:8765/`) yourself. |
| No window | Look behind other windows. Run `python -m cfsim.viewer --check`; it tells you what is missing. |
| The drone does nothing | Read the `[cfsim]` messages in the terminal: not armed, thrust lock, crashed, battery empty, ... |
| The drone crashes into a wall | Expected – it happens on the real drone too. Use the Multi-ranger to keep a distance. |
