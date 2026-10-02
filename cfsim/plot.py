"""Pictures of the simulation for Jupyter notebooks.

cfsim.show()    draws the world, the drones and their flight paths below the cell
cfsim.replay()  plays the recorded flight back as an animation below the cell
live view       a picture below the running cell that follows the drones
                (switched on automatically in notebooks, see notebook.py)
"""
import bisect
import io
import math
import os
import tempfile

from .engine import get_engine

CRASH_COLOR = '#d62828'


class Scene:
    """The world plus one set of artists per drone; update() moves them."""

    def __init__(self, fig, world):
        from matplotlib.patches import Rectangle
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection

        self.fig = fig
        self.world = world
        self.ax3 = ax3 = fig.add_subplot(1, 2, 1, projection='3d')
        self.ax2 = ax2 = fig.add_subplot(1, 2, 2)
        self.artists = {}

        faces = []
        for (x1, y1, x2, y2) in world.boxes:
            p = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
            for i in range(4):
                (ax_, ay_), (bx_, by_) = p[i], p[(i + 1) % 4]
                faces.append([(ax_, ay_, 0), (bx_, by_, 0), (bx_, by_, world.height),
                              (ax_, ay_, world.height)])
            ax2.add_patch(Rectangle((x1, y1), x2 - x1, y2 - y1, facecolor='#5c6672'))
        if faces:
            ax3.add_collection3d(Poly3DCollection(faces, facecolor='#9aa4b1',
                                                  edgecolor='#9aa4b1', linewidths=0.2,
                                                  alpha=0.13))
        bx, by = world.beacon
        ax2.plot([bx], [by], marker='^', color='#2a9d8f', ms=8, ls='none')

        xmin, xmax, ymin, ymax = world.bounds
        ax3.set_xlim(xmin, xmax)
        ax3.set_ylim(ymin, ymax)
        ax3.set_zlim(0, world.height)
        try:
            ax3.set_box_aspect((xmax - xmin, ymax - ymin, world.height))
        except Exception:
            pass
        ax3.set_xlabel('x (m)')
        ax3.set_ylabel('y (m)')
        ax3.set_zlabel('z (m)')
        ax2.set_xlim(xmin, xmax)
        ax2.set_ylim(ymin, ymax)
        ax2.set_aspect('equal')
        ax2.grid(True, color='#e3e6ea')
        self.set_time(0.0)
        fig.tight_layout()

    def set_time(self, t):
        self.ax2.set_title(f"world '{self.world.name}' - top view, t = {t:.1f} s",
                           fontsize=10)

    def update(self, t, drones):
        """drones: dicts with uri, label, color, model, trail, pos, yaw, crashed."""
        self.set_time(t)
        new = False
        for d in drones:
            a = self.artists.get(d['uri'])
            if a is None:
                c = d['color']
                a = self.artists[d['uri']] = {
                    'line3': self.ax3.plot([], [], [], color=c, lw=1.2)[0],
                    'line2': self.ax2.plot([], [], color=c, lw=1.2,
                                           label=f"{d['label']} ({d['model']})")[0],
                    'dot3': self.ax3.plot([], [], [], 'o', color=c, ms=8)[0],
                    'dot2': self.ax2.plot([], [], 'o', color=c, ms=8)[0],
                    'head': self.ax2.plot([], [], color=CRASH_COLOR, lw=2)[0],
                }
                new = True
            trail = d['trail']
            if trail:
                xs, ys, zs = zip(*trail)
                a['line3'].set_data_3d(xs, ys, zs)
                a['line2'].set_data(xs, ys)
            x, y, z = d['pos']
            a['dot3'].set_data_3d([x], [y], [z])
            a['dot2'].set_data([x], [y])
            for k in ('dot3', 'dot2'):
                a[k].set_marker('X' if d['crashed'] else 'o')
                a[k].set_color(CRASH_COLOR if d['crashed'] else d['color'])
            h = math.radians(d['yaw'])
            a['head'].set_data([x, x + 0.25 * math.cos(h)], [y, y + 0.25 * math.sin(h)])
        if new:
            self.ax2.legend(fontsize=8, loc='upper right')

    def png(self, dpi=80):
        buf = io.BytesIO()
        self.fig.savefig(buf, format='png', dpi=dpi)
        return buf.getvalue()


def snapshot(eng):
    """The current state of all drones, in the form Scene.update() wants."""
    with eng.lock:
        return eng.now(), [{'uri': d.uri, 'label': d.label, 'color': d.m['color'],
                            'model': d.m['label'], 'trail': list(d.trail),
                            'pos': tuple(d.pos), 'yaw': d.yaw, 'crashed': d.crashed}
                           for d in eng.drones_list()]


def new_figure(figsize):
    """A figure that is not managed by pyplot, so notebooks don't show it by
    themselves (and it can be drawn from a background thread)."""
    from matplotlib.figure import Figure
    return Figure(figsize=figsize)


def show(figsize=(12, 5)):
    import matplotlib.pyplot as plt
    eng = get_engine()
    scene = Scene(plt.figure(figsize=figsize), eng.world)
    scene.update(*snapshot(eng))
    plt.show()


def replay(speed=1.0, fps=8, figsize=(10, 4), max_frames=200):
    """Animate the recorded flight. Returns an HTML player for the notebook."""
    import matplotlib
    from matplotlib.animation import FuncAnimation, HTMLWriter
    try:
        from IPython.display import HTML
    except ImportError:
        raise RuntimeError('cfsim.replay() is meant for Jupyter notebooks. In a script, '
                           'watch the flight in the 3D window instead.') from None

    eng = get_engine()
    with eng.lock:
        samples = list(eng.history)
        info = dict(eng.history_info)
    if len(samples) < 2:
        print('[cfsim] Nothing to replay yet: fly first, then call cfsim.replay().')
        return None

    # Playback time: real time, but long pauses (nothing moving) are cut short
    play = [0.0]
    for (t0, _), (t1, _) in zip(samples, samples[1:]):
        play.append(play[-1] + min(t1 - t0, 0.25))
    total = play[-1]
    n = int(total * fps / speed) + 1
    if n > max_frames:
        speed = total * fps / (max_frames - 1)
        n = max_frames
        print(f'[cfsim] Long flight: replaying at {speed:.1f}x speed '
              f'(use max_frames=... for a slower replay).')

    # Trails: for each drone the sample numbers and positions it was seen at
    seen = {}
    for i, (_, drones) in enumerate(samples):
        for uri, x, y, z, _yaw, _crashed in drones:
            idx, pts = seen.setdefault(uri, ([], []))
            idx.append(i)
            pts.append((x, y, z))

    def state(i):
        t, drones = samples[i]
        out = []
        for uri, x, y, z, yaw, crashed in drones:
            idx, pts = seen[uri]
            k = bisect.bisect_right(idx, i)
            label, color, model = info[uri]
            out.append({'uri': uri, 'label': label, 'color': color, 'model': model,
                        'trail': pts[:k], 'pos': (x, y, z), 'yaw': yaw,
                        'crashed': crashed})
        return t, out

    fig = new_figure(figsize)
    scene = Scene(fig, eng.world)

    def frame(f):
        i = min(bisect.bisect_right(play, f * speed / fps) - 1, len(samples) - 1)
        scene.update(*state(i))
        return []

    # Like anim.to_jshtml(), but with JPEG frames: about 3 MB for a 15 s flight
    anim = FuncAnimation(fig, frame, frames=n, interval=1000 / fps)
    with matplotlib.rc_context({'animation.frame_format': 'jpeg',
                                'animation.embed_limit': 60}), \
            tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, 'replay.html')
        anim.save(path, dpi=72, writer=HTMLWriter(fps=fps, embed_frames=True,
                                                  default_mode='once'),
                  savefig_kwargs={'pil_kwargs': {'quality': 70}})
        with open(path, encoding='utf-8') as f:
            html = f.read()
    return HTML(html)
