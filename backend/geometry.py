"""Pure geometry / resolver primitives (unit-tested in backend/tests)."""
import math
import numpy as np

SNAP_EVENTS = ["ball_snap", "autoevent_ballsnap"]
END_EVENTS = ["pass_forward", "autoevent_passforward", "qb_sack", "qb_strip_sack", "run"]


def distance(p, q):
    return math.hypot(p[0] - q[0], p[1] - q[1])


def flip_dir(d):
    return (d + 180) % 360


def shoelace(poly):
    n = len(poly)
    return 0.5 * abs(sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1] for i in range(n)))


def convex_hull(pts):
    """Monotone chain; returns hull vertices counter-clockwise."""
    pts = sorted(set(map(tuple, pts)))
    if len(pts) < 3: return pts
    cross = lambda o, a, b: (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, up = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0: lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0: up.pop()
        up.append(p)
    return lo[:-1] + up[:-1]


def pocket_area(pts):
    return shoelace(convex_hull(pts))


def resolve_play_frames(ev):
    """ev: DataFrame[frameId, event] for one play -> (snap, end, resolved, reason)."""
    snap = end = None
    for e in SNAP_EVENTS:
        f = ev.frameId[ev.event == e]
        if len(f): snap = int(f.min()); break
    for e in END_EVENTS:
        f = ev.frameId[ev.event == e]
        if len(f): end = int(f.min()); break
    if snap is None: return None, None, False, "no snap event"
    if end is None: return snap, None, False, "no end-of-dropback event"
    if end <= snap: return snap, end, False, "end precedes snap"
    return snap, end, True, ""


def first_run(mask, n):
    """Index of the first run of >= n consecutive True values, else -1."""
    run = 0
    for i, m in enumerate(mask):
        run = run + 1 if m else 0
        if run >= n: return i - n + 1
    return -1


def wilson(k, n, conf=0.90):
    if n == 0: return 0.0, 0.0
    z = {0.90: 1.6449, 0.95: 1.96}[conf]
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)
