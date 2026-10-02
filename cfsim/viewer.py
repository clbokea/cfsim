"""Live view of the simulation: a 3D view and a top-down map.

Runs as its own process (started by the engine) and reads the simulation
state as JSON lines on stdin. Close the window at any time; the simulation
keeps running without it."""
import json
import math
import os
import sys
import threading

_state = {'world': None, 'drones': [], 'trails': {}, 't': 0.0, 'msgs': [], 'ended': False}
_lock = threading.Lock()


def _reader():
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        with _lock:
            kind = msg.get('type')
            if kind == 'world':
                _state['world'] = msg['world']
            elif kind == 'state':
                _state['drones'] = msg['drones']
                _state['t'] = msg['t']
                if 'trails' in msg:
                    _state['trails'] = msg['trails']
            elif kind == 'msg':
                _state['msgs'] = (_state['msgs'] + [msg['text']])[-3:]
            elif kind == 'end':
                _state['ended'] = True
    with _lock:
        _state['ended'] = True


def _box_faces(x1, y1, x2, y2, h):
    p = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    faces = []
    for i in range(4):
        (ax, ay), (bx, by) = p[i], p[(i + 1) % 4]
        faces.append([(ax, ay, 0), (bx, by, 0), (bx, by, h), (ax, ay, h)])
    faces.append([(x, y, h) for x, y in p])
    return faces


def main():
    snapshot = os.environ.get('CFSIM_SNAPSHOT')
    import matplotlib
    if snapshot:
        matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation
    from matplotlib.patches import Rectangle
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    threading.Thread(target=_reader, daemon=True).start()

    # Wait for the world description
    import time
    for _ in range(200):
        with _lock:
            if _state['world'] is not None:
                break
        time.sleep(0.05)
    with _lock:
        world = _state['world']
    if world is None:
        return

    xmin, xmax, ymin, ymax = world['bounds']
    height = world['height']

    fig = plt.figure(figsize=(13, 6.8))
    try:
        fig.canvas.manager.set_window_title(f"cfsim - {world['name']}")
    except Exception:
        pass
    gs = fig.add_gridspec(2, 2, width_ratios=[1.35, 1], height_ratios=[5, 1.5],
                          left=0.02, right=0.98, top=0.89, bottom=0.02,
                          wspace=0.08, hspace=0.12)
    ax3 = fig.add_subplot(gs[0, 0], projection='3d')
    ax2 = fig.add_subplot(gs[0, 1])
    axt = fig.add_subplot(gs[1, :])
    axt.axis('off')

    # ---- 3D view
    faces = []
    for (x1, y1, x2, y2) in world['boxes']:
        faces += _box_faces(x1, y1, x2, y2, height)
    if faces:
        ax3.add_collection3d(Poly3DCollection(faces, facecolor='#9aa4b1', edgecolor='#9aa4b1',
                                              linewidths=0.2, alpha=0.13))
    ax3.plot([xmin, xmax, xmax, xmin, xmin], [ymin, ymin, ymax, ymax, ymin], [0] * 5,
             color='#b0b7c0', lw=0.8)
    bx, by = world['beacon']
    ax3.scatter([bx], [by], [0], marker='^', color='#2a9d8f', s=40)
    ax3.set_xlim(xmin, xmax)
    ax3.set_ylim(ymin, ymax)
    ax3.set_zlim(0, height)
    try:
        ax3.set_box_aspect((xmax - xmin, ymax - ymin, height))
    except Exception:
        pass
    ax3.set_xlabel('x (m)')
    ax3.set_ylabel('y (m)')
    ax3.set_zlabel('z (m)')
    ax3.view_init(elev=28, azim=-60)

    # ---- top view
    for (x1, y1, x2, y2) in world['boxes']:
        ax2.add_patch(Rectangle((x1, y1), x2 - x1, y2 - y1, facecolor='#5c6672',
                                edgecolor='none'))
    ax2.plot([bx], [by], marker='^', color='#2a9d8f', ms=8, ls='none')
    ax2.set_xlim(xmin, xmax)
    ax2.set_ylim(ymin, ymax)
    ax2.set_aspect('equal')
    ax2.grid(True, color='#e3e6ea', lw=0.6)
    ax2.set_xlabel('Top view  (triangle = home / radio beacon)', fontsize=9)
    ax2.tick_params(labelsize=8)

    info = axt.text(0.0, 1.0, '', va='top', ha='left', family='monospace', fontsize=9,
                    transform=axt.transAxes)
    msgs = fig.text(0.5, 0.945, '', va='top', ha='center', fontsize=8.5, color='#b23a2b')
    title = fig.suptitle('', fontsize=11)

    artists = {}

    def make(d):
        c = d['color']
        a = {
            'body3': ax3.plot([], [], [], 'o', color=c, ms=8)[0],
            'arm1': ax3.plot([], [], [], '-', color=c, lw=2)[0],
            'arm2': ax3.plot([], [], [], '-', color=c, lw=2)[0],
            'head3': ax3.plot([], [], [], '-', color='#d62828', lw=2)[0],
            'drop3': ax3.plot([], [], [], ':', color=c, lw=0.8)[0],
            'trail3': ax3.plot([], [], [], '-', color=c, lw=1, alpha=0.6)[0],
            'body2': ax2.plot([], [], 'o', color=c, ms=7)[0],
            'head2': ax2.plot([], [], '-', color='#d62828', lw=2)[0],
            'trail2': ax2.plot([], [], '-', color=c, lw=1, alpha=0.6)[0],
            'rays': [ax2.plot([], [], '-', color='#f4a261', lw=0.7, alpha=0.55)[0]
                     for _ in range(4)],
            'label2': ax2.text(0, 0, d['label'], fontsize=8, color=c),
        }
        artists[d['id']] = a
        return a

    def update(_frame):
        with _lock:
            drones = list(_state['drones'])
            trails = dict(_state['trails'])
            t = _state['t']
            m = list(_state['msgs'])
            ended = _state['ended']
        lines = []
        for d in drones:
            a = artists.get(d['id']) or make(d)
            x, y, z, yaw = d['x'], d['y'], d['z'], math.radians(d['yaw'])
            crashed = d['crashed']
            a['body3'].set_data_3d([x], [y], [z])
            a['body3'].set_marker('X' if crashed else 'o')
            a['body3'].set_color('#d62828' if crashed else d['color'])
            r = 0.09
            for k, arm in enumerate((a['arm1'], a['arm2'])):
                ang = yaw + math.pi / 4 + k * math.pi / 2
                arm.set_data_3d([x - r * math.cos(ang), x + r * math.cos(ang)],
                                [y - r * math.sin(ang), y + r * math.sin(ang)], [z, z])
            hx, hy = x + 0.18 * math.cos(yaw), y + 0.18 * math.sin(yaw)
            a['head3'].set_data_3d([x, hx], [y, hy], [z, z])
            a['drop3'].set_data_3d([x, x], [y, y], [0, z])
            a['body2'].set_data([x], [y])
            a['body2'].set_marker('X' if crashed else 'o')
            a['body2'].set_color('#d62828' if crashed else d['color'])
            a['head2'].set_data([x, x + 0.25 * math.cos(yaw)], [y, y + 0.25 * math.sin(yaw)])
            a['label2'].set_position((x + 0.08, y + 0.08))
            tr = trails.get(d['id'])
            if tr:
                xs, ys, zs = zip(*tr)
                a['trail3'].set_data_3d(xs, ys, zs)
                a['trail2'].set_data(xs, ys)
            rg = d.get('ranges')
            for ray, ang in zip(a['rays'], (0, 90, 180, -90)):
                key = {0: 'front', 90: 'left', 180: 'back', -90: 'right'}[ang]
                if rg and rg.get(key) is not None and z > 0.03:
                    dist = rg[key]
                    aa = yaw + math.radians(ang)
                    ray.set_data([x, x + dist * math.cos(aa)], [y, y + dist * math.sin(aa)])
                else:
                    ray.set_data([], [])
            if crashed:
                status = 'CRASHED'
            elif d['motors'] and z > 0.02:
                status = 'flying'
            elif d['motors']:
                status = 'motors on'
            else:
                status = 'on ground'
            lines.append(f"{d['label']:<8} {d['model']:<24} x={x:6.2f} y={y:6.2f} "
                         f"z={z:5.2f} m  yaw={d['yaw']:7.1f}  bat={d['vbat']:.2f} V  {status}")
        info.set_text('\n'.join(lines) if lines else 'Waiting for a drone to connect ...')
        msgs.set_text(m[-1][-150:] if m else '')
        suffix = '   - script finished (close this window)' if ended else ''
        title.set_text(f"cfsim  |  world: {world['name']}  |  t = {t:5.1f} s{suffix}")
        return []

    if snapshot:
        deadline = time.time() + float(os.environ.get('CFSIM_SNAPSHOT_AFTER', '8'))
        while time.time() < deadline:
            with _lock:
                if _state['ended']:
                    break
            time.sleep(0.1)
        update(0)
        fig.savefig(snapshot, dpi=90)
        return

    anim = FuncAnimation(fig, update, interval=60, cache_frame_data=False)  # noqa: F841
    plt.show()


if __name__ == '__main__':
    main()
