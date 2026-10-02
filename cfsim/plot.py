"""cfsim.show(): draw the world, the drones and their flight paths in the
current process - in a Jupyter notebook the picture appears below the cell."""
import math

from .engine import get_engine


def show(figsize=(12, 5)):
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    eng = get_engine()
    w = eng.world
    with eng.lock:
        drones = [(d.label, d.m['color'], d.m['label'], list(d.trail), tuple(d.pos), d.yaw,
                   d.crashed) for d in eng.drones_list()]

    xmin, xmax, ymin, ymax = w.bounds
    fig = plt.figure(figsize=figsize)
    ax3 = fig.add_subplot(1, 2, 1, projection='3d')
    ax2 = fig.add_subplot(1, 2, 2)

    faces = []
    for (x1, y1, x2, y2) in w.boxes:
        p = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
        for i in range(4):
            (ax_, ay_), (bx_, by_) = p[i], p[(i + 1) % 4]
            faces.append([(ax_, ay_, 0), (bx_, by_, 0), (bx_, by_, w.height), (ax_, ay_, w.height)])
        ax2.add_patch(Rectangle((x1, y1), x2 - x1, y2 - y1, facecolor='#5c6672'))
    if faces:
        ax3.add_collection3d(Poly3DCollection(faces, facecolor='#9aa4b1',
                                              edgecolor='#9aa4b1', linewidths=0.2, alpha=0.13))
    bx, by = w.beacon
    ax2.plot([bx], [by], marker='^', color='#2a9d8f', ms=8, ls='none')

    for label, color, model, trail, pos, yaw, crashed in drones:
        if trail:
            xs, ys, zs = zip(*trail)
            ax3.plot(xs, ys, zs, color=color, lw=1.2)
            ax2.plot(xs, ys, color=color, lw=1.2, label=f'{label} ({model})')
        mk = 'X' if crashed else 'o'
        c = '#d62828' if crashed else color
        ax3.plot([pos[0]], [pos[1]], [pos[2]], mk, color=c, ms=8)
        ax2.plot([pos[0]], [pos[1]], mk, color=c, ms=8)
        a = math.radians(yaw)
        ax2.plot([pos[0], pos[0] + 0.25 * math.cos(a)], [pos[1], pos[1] + 0.25 * math.sin(a)],
                 color='#d62828', lw=2)

    ax3.set_xlim(xmin, xmax)
    ax3.set_ylim(ymin, ymax)
    ax3.set_zlim(0, w.height)
    try:
        ax3.set_box_aspect((xmax - xmin, ymax - ymin, w.height))
    except Exception:
        pass
    ax3.set_xlabel('x (m)')
    ax3.set_ylabel('y (m)')
    ax3.set_zlabel('z (m)')
    ax2.set_xlim(xmin, xmax)
    ax2.set_ylim(ymin, ymax)
    ax2.set_aspect('equal')
    ax2.grid(True, color='#e3e6ea')
    ax2.set_title(f"world '{w.name}' - top view, t = {eng.now():.1f} s", fontsize=10)
    if drones:
        ax2.legend(fontsize=8, loc='upper right')
    fig.tight_layout()
    plt.show()
