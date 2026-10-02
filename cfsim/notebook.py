"""Live view in Jupyter notebooks: a picture below the running cell that
follows the drones while they fly (also in online notebooks without a window).

When a cell connects to a drone (SyncCrazyflie / Swarm), a picture is put
below that cell. A background thread redraws it a few times per second while
something moves. Switch it off with cfsim.enable(inline=False).
"""
import contextvars
import threading
import time

PERIOD_S = 0.3           # time between pictures
FIGSIZE = (10, 4)

_lock = threading.Lock()
_view = {'cell': None, 'handle': None, 'ctx': None, 'scene': None, 'last': None,
         'thread': None}


def in_notebook():
    try:
        from IPython import get_ipython
    except ImportError:
        return False
    ip = get_ipython()
    return ip is not None and getattr(ip, 'kernel', None) is not None


def on_connect():
    """Called in the cell's own thread when a script connects to a drone."""
    from .engine import _config, get_engine
    if not _config['inline'] or not in_notebook():
        return
    from IPython import get_ipython
    from IPython.display import Image, display
    from . import plot

    cell = get_ipython().execution_count
    with _lock:
        if _view['cell'] == cell:              # e.g. a swarm: one picture per cell
            return
        eng = get_engine()
        if _view['scene'] is None:
            _view['scene'] = plot.Scene(plot.new_figure(FIGSIZE), eng.world)
        scene = _view['scene']
        state = plot.snapshot(eng)
        scene.update(*state)
        _view.update(cell=cell, last=_key(state),
                     handle=display(Image(scene.png()), display_id=True),
                     # messages from our thread must belong to this cell
                     ctx=contextvars.copy_context())
        if _view['thread'] is None:
            _view['thread'] = threading.Thread(target=_run, name='cfsim-live', daemon=True)
            _view['thread'].start()


def _key(state):
    t, drones = state
    return tuple((round(d['pos'][0], 2), round(d['pos'][1], 2), round(d['pos'][2], 2),
                  round(d['yaw']), d['crashed']) for d in drones)


def _run():
    from IPython.display import Image
    from . import plot
    from .engine import get_engine
    eng = get_engine()
    while True:
        time.sleep(PERIOD_S)
        try:
            with _lock:
                state = plot.snapshot(eng)
                key = _key(state)
                if key == _view['last']:
                    continue
                _view['last'] = key
                _view['scene'].update(*state)
                img = Image(_view['scene'].png())
                handle, ctx = _view['handle'], _view['ctx']
            ctx.run(handle.update, img)
        except Exception:                      # never disturb the flight
            pass
