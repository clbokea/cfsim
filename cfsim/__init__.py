"""cfsim - a lightweight Crazyflie simulator for the classroom.

Write normal cflib scripts. Run them in the simulator in one of two ways:

    python -m cfsim my_script.py            # no changes to the script at all

or put these two lines at the very top of the script (before any cflib import):

    import cfsim
    cfsim.enable()                          # remove this line to fly the real drone

Options (for enable() and the command line) - see README.md.
"""
import importlib
import importlib.abc
import importlib.util
import sys

__version__ = '1.0.4'
__all__ = ['enable', 'is_enabled', 'worlds', 'show', 'replay', 'reset']

_enabled = False


class _CflibAliasLoader(importlib.abc.Loader):
    def __init__(self, real_name):
        self.real_name = real_name

    def create_module(self, spec):
        return importlib.import_module(self.real_name)

    def exec_module(self, module):
        pass


class _CflibAliasFinder(importlib.abc.MetaPathFinder):
    """Makes `import cflib.xyz` load `cfsim._cflib.xyz`."""

    def find_spec(self, fullname, path=None, target=None):
        if fullname != 'cflib' and not fullname.startswith('cflib.'):
            return None
        real = 'cfsim._cflib' + fullname[len('cflib'):]
        try:
            spec = importlib.util.find_spec(real)
        except ModuleNotFoundError:
            spec = None
        if spec is None:
            raise ImportError(
                f"'{fullname}' is not available in the cfsim simulator. "
                f"Supported: cflib.crtp, cflib.crazyflie (Crazyflie, log, syncCrazyflie, "
                f"syncLogger, swarm), cflib.positioning (motion_commander, "
                f"position_hl_commander), cflib.utils (uri_helper, multiranger).",
                name=fullname)
        return importlib.util.spec_from_loader(
            fullname, _CflibAliasLoader(real),
            is_package=spec.submodule_search_locations is not None)


def enable(world='room', model='2.1+', positioning='flow', noise=True,
           decks=('flow', 'multiranger'), viewer=True, battery_drain=1.0,
           models=None, start_positions=None, quiet=False, inline=True):
    """Switch cflib to the simulator. Call before importing anything from cflib.

    world:           'room', 'corridor', 'maze', 'obstacles', 'arena', 'open'
                     or the path to your own .txt map
    model:           '2.1+' or 'brushless' (default for all drones)
    models:          {uri: model} to mix models, e.g. one brushless drone
    positioning:     'flow' (Flow deck: relative to take-off spot, drifts),
                     'lighthouse' (absolute, accurate) or 'none'
    noise:           sensor noise and position drift on/off
    decks:           which decks are mounted: 'flow', 'multiranger'
    viewer:          open the live view window
    battery_drain:   e.g. 10 makes the battery run out 10x faster
    start_positions: {uri: (x, y)} to place drones yourself
    quiet:           do not print simulator messages
    inline:          in a Jupyter notebook, show a live picture below the
                     running cell (False: only the separate window)
    """
    global _enabled
    existing = sys.modules.get('cflib')
    if existing is not None and not getattr(existing, 'SIMULATED', False):
        raise RuntimeError(
            'cflib was imported before cfsim.enable(). Put "import cfsim" and '
            '"cfsim.enable()" at the very top of your script, before any cflib import.')
    from . import engine
    engine.configure(world=world, model=model, positioning=positioning, noise=noise,
                     decks=decks, viewer=viewer, battery_drain=battery_drain,
                     models=dict(models or {}),
                     start_positions=dict(start_positions or {}), quiet=quiet,
                     inline=inline)
    engine.World.load(world)                 # fail early on a bad world name
    if not _enabled:
        sys.meta_path.insert(0, _CflibAliasFinder())
        _enabled = True


def is_enabled():
    return _enabled


def worlds():
    from .world import builtin_worlds
    return builtin_worlds()


def show(figsize=(12, 5)):
    """Draw the world, drones and flight paths in this process.
    In a Jupyter notebook the picture appears below the cell."""
    from .plot import show as _show
    _show(figsize)


def replay(speed=1.0, fps=8, figsize=(10, 4), max_frames=200):
    """Play the recorded flight back as an animation (in a Jupyter notebook,
    below the cell). speed=2 plays twice as fast. Long pauses are shortened."""
    from .plot import replay as _replay
    return _replay(speed=speed, fps=fps, figsize=figsize, max_frames=max_frames)


def reset():
    """Remove all simulated drones (they reappear at their start spots the
    next time a script connects) and forget the recorded flight.
    Handy for re-running notebook cells.
    Call it after all `with SyncCrazyflie(...)` blocks have finished."""
    from .engine import get_engine
    eng = get_engine()
    with eng.lock:
        eng.drones.clear()
        eng.history.clear()
    eng.message('reset: all drones removed')
