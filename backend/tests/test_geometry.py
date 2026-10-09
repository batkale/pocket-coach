import os, random, sys
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from geometry import distance, flip_dir, shoelace, pocket_area, resolve_play_frames, first_run, wilson


def test_distance_symmetric_nonnegative():
    for _ in range(200):
        p, q = (random.uniform(0, 120), random.uniform(0, 53.3)), (random.uniform(0, 120), random.uniform(0, 53.3))
        assert distance(p, q) == distance(q, p) >= 0
    assert distance((0, 0), (3, 4)) == 5


def test_flip_involutive():
    for d in range(0, 360, 7):
        assert abs(flip_dir(flip_dir(d)) - d) < 1e-9


def test_shoelace_square():
    assert shoelace([(0, 0), (2, 0), (2, 2), (0, 2)]) == 4


def test_pocket_area_unordered_with_interior_point():
    pts = [(2, 2), (0, 0), (0, 3), (1, 1), (4, 0), (4, 3)]  # 4x3 rectangle + interior points
    for _ in range(50):
        random.shuffle(pts)
        assert abs(pocket_area(pts) - 12) < 1e-9


def ev(rows):
    return pd.DataFrame(rows, columns=["frameId", "event"])


def test_resolver_prefers_manual_and_handles_unresolved():
    assert resolve_play_frames(ev([(11, "autoevent_ballsnap"), (10, "ball_snap"), (30, "pass_forward")]))[:3] == (10, 30, True)
    assert resolve_play_frames(ev([(11, "autoevent_ballsnap"), (25, "qb_sack")]))[:3] == (11, 25, True)
    assert resolve_play_frames(ev([(30, "pass_forward")]))[2] is False
    assert resolve_play_frames(ev([(10, "ball_snap")]))[2] is False
    assert resolve_play_frames(ev([(40, "ball_snap"), (30, "pass_forward")]))[2] is False


def test_engagement_needs_three_consecutive_frames():
    assert first_run([True, True, False, True, True, True], 3) == 3
    assert first_run([True, True, False, True, True], 3) == -1


def test_wilson_bounds():
    for k, n in [(0, 10), (3, 10), (10, 10), (7, 250)]:
        lo, hi = wilson(k, n)
        assert 0 <= lo <= k / n <= hi <= 1
