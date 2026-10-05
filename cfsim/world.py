"""Worlds: walls, ray casting for range sensors, and collision checks.

A world is drawn as a text map, one character per cell (0.5 m by default):

    '#'      wall (full height, from floor to ceiling)
    'S'      start position of the first drone (and the radio beacon)
    '1'-'9'  extra start positions (for swarms)
    'B'      radio beacon position (optional, default = start)
    '.' ' '  free space

Lines starting with ';' are comments. Optional settings at the top:

    height: 2.5     ceiling height in metres
    cell: 0.5       cell size in metres
    image: plan.png               floor plan shown on the floor in the browser
    image_box: x1 y1 x2 y2        where the image lies, in metres (world coordinates)

The room editor (python -m cfsim --editor) writes such maps from a floor plan.

The world origin (0, 0) is the centre of the 'S' cell (or '1' if there is no
'S'). +x points right on the map, +y points up on the map.
"""
import math
import os

BUILTIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'worlds')


def builtin_worlds():
    names = [f[:-4] for f in os.listdir(BUILTIN_DIR) if f.endswith('.txt')]
    return ['open'] + sorted(names)


class World:
    def __init__(self, name, boxes, bounds, height=2.5, starts=None,
                 beacon=(0.0, 0.0), bounded=True, image=None, image_box=None):
        self.name = name
        self.boxes = boxes            # list of (x1, y1, x2, y2), x1 < x2, y1 < y2
        self.bounds = bounds          # (xmin, xmax, ymin, ymax) for the viewer
        self.height = height          # ceiling height (m)
        self.starts = starts or [(0.0, 0.0)]
        self.beacon = beacon
        self.bounded = bounded        # False for 'open' (no ceiling either)
        self.image = image            # path of a floor plan image, or None
        self.image_box = image_box    # (x1, y1, x2, y2) of the image in metres

    # ------------------------------------------------------------------ load
    @classmethod
    def load(cls, name_or_path):
        if name_or_path in (None, '', 'open'):
            return cls('open', [], (-3.0, 3.0, -3.0, 3.0), height=3.0,
                       bounded=False)
        path = name_or_path
        if not os.path.isfile(path):
            path = os.path.join(BUILTIN_DIR, name_or_path + '.txt')
        if not os.path.isfile(path):
            raise ValueError(
                f"Unknown world '{name_or_path}'. Built-in worlds: "
                f"{', '.join(builtin_worlds())} (or give a path to a .txt map)")
        with open(path, encoding='utf-8') as f:
            text = f.read()
        name = os.path.splitext(os.path.basename(path))[0]
        return cls.from_text(text, name, os.path.dirname(os.path.abspath(path)))

    @classmethod
    def from_text(cls, text, name='custom', base_dir='.'):
        height, cell = 2.5, 0.5
        image, image_box = None, None
        grid = []
        for raw in text.splitlines():
            line = raw.rstrip('\n')
            if line.strip().startswith(';'):
                continue
            if ':' in line and not grid:
                key, _, val = line.partition(':')
                key = key.strip().lower()
                if key == 'height':
                    height = float(val)
                    continue
                if key == 'cell':
                    cell = float(val)
                    continue
                if key == 'image':
                    image = os.path.join(base_dir, val.strip())
                    continue
                if key == 'image_box':
                    image_box = tuple(float(v) for v in val.replace(',', ' ').split())
                    if len(image_box) != 4:
                        raise ValueError('image_box needs four numbers: x1 y1 x2 y2')
                    continue
            if line.strip() == '' and not grid:
                continue
            grid.append(line)
        while grid and grid[-1].strip() == '':
            grid.pop()
        if not grid:
            raise ValueError('The world map is empty')

        marks = {}
        for r, row in enumerate(grid):
            for c, ch in enumerate(row):
                if ch in 'S123456789B':
                    marks.setdefault(ch, (r, c))
        origin = marks.get('S') or marks.get('1') or (len(grid) // 2, len(grid[0]) // 2)

        def to_xy(r, c):
            return ((c - origin[1]) * cell, (origin[0] - r) * cell)

        # Merge horizontal runs of '#' into boxes
        boxes = []
        for r, row in enumerate(grid):
            c = 0
            while c < len(row):
                if row[c] == '#':
                    start = c
                    while c < len(row) and row[c] == '#':
                        c += 1
                    x1, y = to_xy(r, start)
                    x2, _ = to_xy(r, c - 1)
                    boxes.append((x1 - cell / 2, y - cell / 2,
                                  x2 + cell / 2, y + cell / 2))
                else:
                    c += 1

        # Merge boxes with the same x-range in neighbouring rows (fewer, bigger boxes)
        merged = True
        while merged:
            merged = False
            boxes.sort(key=lambda b: (b[0], b[2], b[1]))
            out = []
            for b in boxes:
                if out and abs(out[-1][0] - b[0]) < 1e-9 and abs(out[-1][2] - b[2]) < 1e-9 \
                        and abs(out[-1][3] - b[1]) < 1e-9:
                    out[-1] = (out[-1][0], out[-1][1], b[2], b[3])
                    merged = True
                else:
                    out.append(b)
            boxes = out

        starts = []
        if 'S' in marks:
            starts.append(to_xy(*marks['S']))
        for d in '123456789':
            if d in marks:
                starts.append(to_xy(*marks[d]))
        beacon = to_xy(*marks['B']) if 'B' in marks else (starts[0] if starts else (0.0, 0.0))

        ncols = max(len(row) for row in grid)
        xa, ya = to_xy(0, 0)
        xb, yb = to_xy(len(grid) - 1, ncols - 1)
        bounds = (xa - cell / 2, xb + cell / 2, yb - cell / 2, ya + cell / 2)
        if image is not None and not os.path.isfile(image):
            raise ValueError(f'The floor plan image of world {name!r} was not found: {image} '
                             f'(keep it in the same folder as the .txt file)')
        if image is not None and image_box is None:
            image_box = bounds[0], bounds[2], bounds[1], bounds[3]
        return cls(name, boxes, bounds, height, starts or [(0.0, 0.0)], beacon,
                   image=image, image_box=image_box)

    # -------------------------------------------------------------- queries
    def raycast(self, x, y, dx, dy, max_range, circles=()):
        """Distance along the 2D ray (x,y)+t*(dx,dy) to the nearest wall or
        circle (cx, cy, radius). Returns None if nothing within max_range."""
        best = max_range
        for (x1, y1, x2, y2) in self.boxes:
            tmin, tmax = 0.0, best
            hit = True
            for o, d, lo, hi in ((x, dx, x1, x2), (y, dy, y1, y2)):
                if abs(d) < 1e-12:
                    if o < lo or o > hi:
                        hit = False
                        break
                else:
                    t1, t2 = (lo - o) / d, (hi - o) / d
                    if t1 > t2:
                        t1, t2 = t2, t1
                    tmin, tmax = max(tmin, t1), min(tmax, t2)
                    if tmin > tmax:
                        hit = False
                        break
            if hit and tmin < best:
                best = tmin
        for (cx, cy, rad) in circles:
            ox, oy = x - cx, y - cy
            b = ox * dx + oy * dy
            c = ox * ox + oy * oy - rad * rad
            disc = b * b - c
            if disc >= 0:
                t = -b - math.sqrt(disc)
                if 0 <= t < best:
                    best = t
        return None if best >= max_range else best

    def hits_wall(self, x, y, radius):
        for (x1, y1, x2, y2) in self.boxes:
            px = min(max(x, x1), x2)
            py = min(max(y, y1), y2)
            if (x - px) ** 2 + (y - py) ** 2 < radius * radius:
                return True
        return False

    def free_spot(self, x, y, radius=0.15):
        return not self.hits_wall(x, y, radius)

    def to_dict(self):
        return {'name': self.name, 'boxes': self.boxes, 'bounds': self.bounds,
                'height': self.height, 'beacon': self.beacon,
                'bounded': self.bounded, 'starts': self.starts,
                'image_path': self.image, 'image_box': self.image_box}
