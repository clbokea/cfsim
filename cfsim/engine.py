"""The simulation engine: runs physics in real time in a background thread
and streams the state to the viewer window (a separate process)."""
import atexit
import json
import math
import os
import subprocess
import sys
import threading
import time

from .drone import SimDrone, model_name
from .world import World

PHYSICS_HZ = 100
VIEWER_HZ = 20

_engine = None
_config = {
    'world': 'room',
    'model': '2.1+',
    'models': {},              # per-URI model override
    'positioning': 'flow',     # flow | lighthouse | none
    'noise': True,
    'decks': ('flow', 'multiranger'),
    'viewer': True,
    'battery_drain': 1.0,      # 10 = battery drains 10x faster
    'start_positions': {},     # uri -> (x, y)
    'quiet': False,
}


def configure(**options):
    unknown = set(options) - set(_config)
    if unknown:
        raise TypeError(f'Unknown cfsim option(s): {", ".join(sorted(unknown))}. '
                        f'Valid options: {", ".join(sorted(_config))}')
    if _engine is not None and _engine.started:
        _engine.message('cfsim.enable() options are ignored: the simulator is already running.')
        return
    if 'model' in options:
        model_name(options['model'])          # validate early
    if 'positioning' in options and options['positioning'] not in ('flow', 'lighthouse', 'none'):
        raise ValueError("positioning must be 'flow', 'lighthouse' or 'none'")
    if 'decks' in options:
        d = options['decks']
        options['decks'] = tuple(x.strip().lower() for x in
                                 (d.split(',') if isinstance(d, str) else d) if x.strip())
    _config.update(options)


def get_engine():
    global _engine
    if _engine is None:
        _engine = Engine(dict(_config))
    return _engine


class Engine:
    def __init__(self, cfg):
        self.cfg = cfg
        self.world = World.load(cfg['world'])
        self.positioning = cfg['positioning']
        self.noise = cfg['noise']
        self.decks = set(cfg['decks'])
        self.battery_drain = float(cfg['battery_drain'])
        self.drones = {}
        self.lock = threading.RLock()
        self.started = False
        self._t0 = None
        self._viewer = None
        self._viewer_ok = cfg['viewer']
        self._thread = None

    # ------------------------------------------------------------- basics
    def now(self):
        return 0.0 if self._t0 is None else time.monotonic() - self._t0

    def message(self, text):
        if not self.cfg['quiet']:
            print(f'[cfsim] {text}', flush=True)
        self._send({'type': 'msg', 'text': text})

    def drones_list(self):
        return list(self.drones.values())

    def start(self):
        with self.lock:
            if self.started:
                return
            self.started = True
            self._t0 = time.monotonic()
            pos = {'flow': 'Flow deck (relative to take-off spot, drifts)',
                   'lighthouse': 'Lighthouse (absolute)',
                   'none': 'no positioning deck'}[self.positioning]
            self.message(f"simulator started - world '{self.world.name}', "
                         f"positioning: {pos}, noise: {'on' if self.noise else 'off'}")
            if self._viewer_ok:
                self._start_viewer()
            self._thread = threading.Thread(target=self._run, name='cfsim-physics',
                                            daemon=True)
            self._thread.start()

    def get_drone(self, uri):
        with self.lock:
            self.start()
            if uri not in self.drones:
                idx = len(self.drones)
                start = self._start_position(uri, idx)
                model = self.cfg['models'].get(uri, self.cfg['model'])
                d = SimDrone(self, uri, idx, start, model)
                self.drones[uri] = d
                self.message(f'drone {d.label} = {uri} ({d.m["label"]}) placed at '
                             f'x={start[0]:.2f} y={start[1]:.2f}')
            return self.drones[uri]

    def _start_position(self, uri, idx):
        if uri in self.cfg['start_positions']:
            return tuple(self.cfg['start_positions'][uri])
        starts = self.world.starts
        taken = [(d.start[0], d.start[1]) for d in self.drones.values()]
        for s in starts:
            if all(math.dist(s, t) > 0.2 for t in taken):
                return s
        # Spiral around the first start spot until a free place is found
        sx, sy = starts[0]
        for ring in range(1, 30):
            for k in range(8 * ring):
                a = 2 * math.pi * k / (8 * ring)
                p = (sx + 0.4 * ring * math.cos(a), sy + 0.4 * ring * math.sin(a))
                if self.world.free_spot(*p) and all(math.dist(p, t) > 0.3 for t in taken):
                    return (round(p[0], 2), round(p[1], 2))
        return (sx, sy)

    # ------------------------------------------------------------- physics
    def _run(self):
        dt = 1.0 / PHYSICS_HZ
        next_t = time.monotonic()
        last_view = 0.0
        self._frame = 0
        while True:
            now_wall = time.monotonic()
            if now_wall < next_t:
                time.sleep(next_t - now_wall)
                continue
            steps = 0
            while next_t <= time.monotonic() and steps < 10:
                with self.lock:
                    now = self.now()
                    for d in self.drones.values():
                        d.step(dt, now)
                    self._drone_collisions()
                next_t += dt
                steps += 1
            if steps >= 10:                       # far behind: skip ahead
                next_t = time.monotonic() + dt
            if self.now() - last_view >= 1.0 / VIEWER_HZ:
                last_view = self.now()
                self._send_state()

    def _drone_collisions(self):
        ds = [d for d in self.drones.values() if not d.on_ground or d.motors]
        for i in range(len(ds)):
            for j in range(i + 1, len(ds)):
                a, b = ds[i], ds[j]
                if math.dist(a.pos, b.pos) < a.m['radius'] + b.m['radius']:
                    a.crash(f'collided with drone {b.label}')
                    b.crash(f'collided with drone {a.label}')

    # -------------------------------------------------------------- viewer
    def _start_viewer(self):
        try:
            import matplotlib  # noqa: F401  (check it is installed)
        except ImportError:
            self.message('matplotlib is not installed, so no viewer window '
                         '(pip install matplotlib). The simulation still runs.')
            self._viewer_ok = False
            return
        env = dict(os.environ)
        pkg_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env['PYTHONPATH'] = pkg_parent + os.pathsep + env.get('PYTHONPATH', '')
        try:
            self._viewer = subprocess.Popen(
                [sys.executable, '-m', 'cfsim.viewer'], stdin=subprocess.PIPE,
                env=env, text=True, bufsize=1)
        except OSError as e:
            self.message(f'could not start the viewer ({e}); running without it.')
            self._viewer_ok = False
            return
        self._send({'type': 'world', 'world': self.world.to_dict()})
        atexit.register(self._final_state)
        self.message('3D view opens in a separate window (it may appear behind this one)')

        def watch(proc):
            code = proc.wait()
            if code == 3:                      # the viewer explained the problem itself
                self._viewer = None
        threading.Thread(target=watch, args=(self._viewer,), daemon=True).start()

    def _send(self, obj):
        v = self._viewer
        if v is None:
            return
        try:
            v.stdin.write(json.dumps(obj) + '\n')
            v.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            self._viewer = None            # window was closed; keep simulating

    def _send_state(self, final=False):
        if self._viewer is None:
            return
        self._frame = getattr(self, '_frame', 0) + 1
        with self.lock:
            drones = [d.state_for_viewer() for d in self.drones.values()]
            msg = {'type': 'state', 't': round(self.now(), 2), 'drones': drones}
            if self._frame % 4 == 0 or final:
                msg['trails'] = {d.uri: d.trail[-600:] for d in self.drones.values()}
        self._send(msg)

    def _final_state(self):
        # Let falling drones reach the floor before the last picture
        end = time.monotonic() + 1.5
        while time.monotonic() < end:
            with self.lock:
                falling = [d for d in self.drones.values() if not d.motors and not d.on_ground]
            if not falling:
                break
            time.sleep(0.05)
        self._send_state(final=True)
        self._send({'type': 'end'})
        v = self._viewer
        if v is not None:
            try:
                v.stdin.close()
            except OSError:
                pass
