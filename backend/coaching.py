"""Game-plan generator: find where each team's pass protection breaks down more than the league
does, and turn the biggest, statistically supported gaps into coaching points and tactics.

Unit of analysis = a dropback. A dropback is a "breakdown" if it carries any protection flag
(PFF sack / hit / hurry allowed or beaten; Confirmed only). Position rows use per-rep rates instead.
Run after pipeline.py:  python backend/coaching.py  -> frontend/coaching.json
"""
import json, os, sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from geometry import wilson

ROOT = Path(__file__).resolve().parents[1]
RAW = Path(os.environ.get("NFL_RAW", ROOT / "nfl-big-data-bowl-regional-event-data-main" / "data"))
OUT = ROOT / "frontend"
MIN_N = 15          # minimum dropbacks / reps in a situation before we talk about it
MIN_GAP = 0.04      # team must be at least 4 percentage points worse than the league

data = json.load(open(OUT / "data.json"))
fl = pd.DataFrame(data["flags"])
PROT = ["sack_allowed", "hit_allowed", "hurry_allowed", "beaten"]  # Confirmed (PFF-charted) only
fl = fl[fl.errorType.isin(PROT)]

plays = pd.read_csv(RAW / "plays.csv")
pff = pd.read_csv(RAW / "pffScoutingData.csv")
players = pd.read_csv(RAW / "players.csv").set_index("nflId")

# --- per-dropback situation features
rush = pff[pff.pff_role == "Pass Rush"].groupby(["gameId", "playId"]).size().rename("rushers")
pb = plays.join(rush, on=["gameId", "playId"]).dropna(subset=["rushers"])
pb = pb[pb.passResult.notna()]
pb["rush_grp"] = pd.cut(pb.rushers, [0, 4, 5, 11], labels=["4 or fewer rushers", "5-man pressure", "6+ man blitz"]).astype(str)
pb["long"] = pb.yardsToGo >= 7
pb["sit"] = [("3rd/4th & long (7+)" if d >= 3 and l else "3rd/4th & short" if d >= 3 else "1st/2nd down") for d, l in zip(pb.down, pb.long)]
pb["pa"] = pb.pff_playAction.map({1: "Play action", 0: "Straight dropback"})
pb["form"] = pb.offenseFormation.fillna("UNKNOWN").str.title()
pb["drop"] = pb.dropBackType.fillna("UNKNOWN").str.replace("_", " ").str.title()
key = set(zip(fl.gameId, fl.playId))
pb["bad"] = [(g, p) in key for g, p in zip(pb.gameId, pb.playId)]

# time from snap to the error moment, from the replay files of flagged plays
t_err = []
for g, p, fr in zip(fl.gameId, fl.playId, fl.errorFrameId):
    f = OUT / "plays" / f"{g}_{p}.json"
    if f.exists():
        snap = json.load(open(f))["meta"]["snap"]
        t_err.append((fr - snap) / 10)
    else:
        t_err.append(None)
fl["t_err"] = t_err
fl["timing"] = pd.cut(fl.t_err, [-1, 2.5, 3.5, 99], labels=["fast (under 2.5 s)", "normal (2.5-3.5 s)", "late (over 3.5 s)"]).astype(str)

# --- per-rep alignment (who lined up where in protection)
blk = pff[pff.pff_role == "Pass Block"].merge(plays[["gameId", "playId", "possessionTeam"]], on=["gameId", "playId"])
def align(a):
    a = str(a)
    if a in ("LT", "RT"): return {"LT": "Left tackle", "RT": "Right tackle"}[a]
    if a in ("LG", "RG"): return {"LG": "Left guard", "RG": "Right guard"}[a]
    if a == "C": return "Center"
    if a.startswith("HB") or a.startswith("FB"): return "Running back"
    if a.startswith("TE"): return "Tight end"
    return None
blk["slot"] = blk.pff_positionLinedUp.map(align)
blk = blk.dropna(subset=["slot"])
bad_rep = set(zip(fl.gameId, fl.playId, fl.primary))
blk["bad"] = [(g, p, n) in bad_rep for g, p, n in zip(blk.gameId, blk.playId, blk.nflId)]

TACTIC = {  # (what to tell players, scheme / tactic)  for self-scout; opponent text is built separately
    "6+ man blitz": ("Backs and tight ends: scan inside-out, take the most dangerous rusher first. QB: know your hot throw before the snap.",
                     "Call 6- or 7-man protection or keep the back in, and pair it with hot routes and quick slants so the blitz is punished."),
    "5-man pressure": ("Linemen: communicate the Mike and slide toward the extra rusher. Back: check before releasing.",
                       "Slide protection toward the overload side, and use quick-game concepts to beat the extra rusher."),
    "4 or fewer rushers": ("This is one-on-one losses, not numbers. Win with hands and anchor, and don't overset.",
                           "Give chip help (RB/TE) to the weak tackle and move the launch point with boots and rollouts."),
    "3rd/4th & long (7+)": ("Everyone: the defense knows you must throw. Expect stunts and delayed blitzes and pass them off.",
                            "Use max protection on obvious passing downs, with screens and draws to slow the rush down."),
    "3rd/4th & short": ("Stay square and expect pressure off the edge. The ball comes out fast.",
                        "Use quick-game or play-action keepers with an extra blocker on the edge."),
    "1st/2nd down": ("Base downs: recognize your run-pass keys and set fast.",
                     "Use more play action on early downs to slow down the pass rush."),
    "Play action": ("Linemen: sell the run but get depth to the set point fast. Back: finish the fake and then pick up.",
                    "Shorten play-action drops or add a 7th blocker. Use boots to move the QB away from the pressure."),
    "Straight dropback": ("Set to depth and keep the pocket firm. QB: climb, don't drift.",
                          "Mix in play action and quick game so the defense can't pin its ears back."),
    "fast (under 2.5 s)": ("Breakdowns happen before the QB can throw, so it's assignment and technique. Drill first-step and hand placement.",
                           "Add help: slide toward the problem side, chip with the back, or call quicker 3-step concepts."),
    "late (over 3.5 s)": ("Protection holds long enough. The QB is holding the ball. Get to the checkdown on time.",
                          "Build in a timing outlet, call more quick-game and RPOs, and coach the QB to throw it away."),
    "Left tackle": ("Left tackle: stay patient, don't overset against speed, and use the inside hand.", "Chip the left edge with the back or TE, or slide the protection left."),
    "Right tackle": ("Right tackle: kick-slide depth and inside hand against power-to-speed.", "Chip the right edge with the back or TE, or slide the protection right."),
    "Left guard": ("Left guard: anchor and reset your hands against bull rushes, and pass off twists.", "Slide the center toward the left guard and use more quick inside throws."),
    "Right guard": ("Right guard: anchor and reset your hands against bull rushes, and pass off twists.", "Slide the center toward the right guard and use more quick inside throws."),
    "Center": ("Center: set the protection call early and pass off loopers.", "Use a double-team call on the nose / A-gap threat."),
    "Running back": ("Backs: blitz pickup. Square up, strike low, and don't duck the shoulder. Scan A-gap to edge.", "Fewer RB-only protection calls, use a chip and release, and send the back out as a hot route."),
    "Tight end": ("Tight ends: inside hand and run your feet. Don't lunge on edge rushers.", "Pair the TE with a back chip, or release the TE to the flat and slide the protection to cover."),
}
ATTACK = {
    "6+ man blitz": "Send 6-man pressure. Their protection breaks down against it.",
    "5-man pressure": "Add a 5th rusher (sim pressure or a blitzing nickel) to overload one side.",
    "4 or fewer rushers": "You can win with four. Rush four, drop seven, and still get home.",
    "3rd/4th & long (7+)": "On 3rd and long, run stunts and twists. Their line struggles to pass them off.",
    "3rd/4th & short": "Pressure the edge on short-yardage passing downs.",
    "1st/2nd down": "Pressure on early downs. They don't protect well before obvious passing downs.",
    "Play action": "Don't bite on play action. Rush hard through the fake, because their play-action protection leaks.",
    "Straight dropback": "Pin your ears back on straight dropbacks.",
    "fast (under 2.5 s)": "Their protection loses quickly. Line up your best rusher on the weak blocker and win at the snap.",
    "late (over 3.5 s)": "Play coverage and keep rush lanes. Their QB holds the ball, so pressure arrives late.",
    "Left tackle": "Put your best edge rusher over their left tackle.",
    "Right tackle": "Put your best edge rusher over their right tackle.",
    "Left guard": "Attack their left guard with power and A/B-gap twists.",
    "Right guard": "Attack their right guard with power and A/B-gap twists.",
    "Center": "Run A-gap pressure and twists at the center.",
    "Running back": "Blitz the linebacker at their running back. Their backs lose in pickup.",
    "Tight end": "Rush the edge over their tight end when he stays in to block.",
}


def compare(df, col, unit, team_col):
    """Team vs league breakdown rate for every value of `col`."""
    lg = df.groupby(col).bad.mean()
    out = []
    for (team, val), g in df.groupby([team_col, col]):
        n, k = len(g), int(g.bad.sum())
        if n < MIN_N: continue
        lo, hi = wilson(k, n)
        out.append(dict(team=team, dim=col, value=val, unit=unit, n=n, k=k, rate=k / n, league=lg[val], lo=lo, hi=hi))
    return out


rows = (compare(pb, "rush_grp", "dropbacks", "possessionTeam") + compare(pb, "sit", "dropbacks", "possessionTeam") +
        compare(pb, "pa", "dropbacks", "possessionTeam") + compare(blk, "slot", "pass-block reps", "possessionTeam"))
res = pd.DataFrame(rows)
res["gap"] = res.rate - res.league
res["strong"] = res.lo > res.league  # 90% interval sits above the league rate

# timing: share of a team's breakdowns that are fast / late vs league share
tm = fl.dropna(subset=["t_err"]).copy()
lgs = tm.timing.value_counts(normalize=True)
trow = []
for team, g in tm.groupby("team"):
    vc = g.timing.value_counts()
    for val in ["fast (under 2.5 s)", "late (over 3.5 s)"]:
        k, n = int(vc.get(val, 0)), len(g)
        lo, hi = wilson(k, n)
        trow.append(dict(team=team, dim="timing", value=val, unit="breakdowns", n=n, k=k, rate=k / n, league=lgs[val], lo=lo, hi=hi,
                         gap=k / n - lgs[val], strong=lo > lgs[val]))
res = pd.concat([res, pd.DataFrame(trow)], ignore_index=True)


def examples(team, dim, val):
    if dim == "timing": f = fl[(fl.team == team) & (fl.timing == val)]
    elif dim == "slot":
        ids = blk[(blk.possessionTeam == team) & (blk.slot == val) & blk.bad]
        f = fl[fl.team == team].merge(ids[["gameId", "playId", "nflId"]], left_on=["gameId", "playId", "primary"], right_on=["gameId", "playId", "nflId"])
    else:
        ps = pb[(pb.possessionTeam == team) & (pb[dim] == val) & pb.bad][["gameId", "playId"]]
        f = fl[fl.team == team].merge(ps, on=["gameId", "playId"])
    f = f.sort_values("epaCost")
    return [dict(play=f"{g}_{p}", frame=int(fr), who=n) for g, p, fr, n in zip(f.gameId, f.playId, f.errorFrameId, f.primaryName)][:3]


def worst_players(team, val):
    b = blk[(blk.possessionTeam == team) & (blk.slot == val)]
    g = b.groupby("nflId").agg(n=("bad", "size"), k=("bad", "sum"))
    g = g[g.n >= 10].sort_values("k", ascending=False).head(2)
    return [f"{players.displayName.get(i, i)} ({int(r.k)} of {int(r.n)} reps)" for i, r in g.iterrows()]


plan = {}
LABEL = {"rush_grp": "vs", "sit": "on", "pa": "on", "slot": "at", "timing": "Breakdowns that are"}
for team, g in res.groupby("team"):
    g = g[(g.gap >= MIN_GAP)].sort_values(["strong", "gap"], ascending=False).head(5)
    items = []
    for r in g.itertuples():
        tell, tactic = TACTIC[r.value]
        if r.dim == "timing":
            head = f"{r.value.split(' (')[0].capitalize()} breakdowns: {r.rate:.0%} of their protection errors are {r.value} (league {r.league:.0%})"
        else:
            head = f"{r.value}: breakdown on {r.rate:.0%} of {r.unit} (league {r.league:.0%})"
        who = worst_players(team, r.value) if r.dim == "slot" else []
        items.append(dict(dim=r.dim, value=r.value, headline=head, n=int(r.n), k=int(r.k), rate=r.rate, league=r.league,
                          lo=r.lo, hi=r.hi, strong=bool(r.strong), tell=tell, tactic=tactic, attack=ATTACK[r.value],
                          players=who, examples=examples(team, r.dim, r.value)))
    # strengths: biggest positive gaps (team better than league), for "keep doing" / "don't attack here"
    s = res[(res.team == team) & (res.gap <= -MIN_GAP) & (res.dim != "timing")].sort_values("gap").head(2)
    strengths = [f"{r.value}: {r.rate:.0%} vs league {r.league:.0%} ({r.n} {r.unit})" for r in s.itertuples()]
    tot = pb[pb.possessionTeam == team]
    plan[team] = dict(dropbacks=len(tot), rate=float(tot.bad.mean()), league=float(pb.bad.mean()), items=items, strengths=strengths)

# league-wide patterns (for the README / overview)
lg = {c: pb.groupby(c).bad.agg(["mean", "size"]).round(3).reset_index().to_dict("records") for c in ["rush_grp", "sit", "pa"]}
lg["slot"] = blk.groupby("slot").bad.agg(["mean", "size"]).round(3).reset_index().to_dict("records")
lg["timing"] = tm.timing.value_counts(normalize=True).round(3).to_dict()
json.dump({"teams": plan, "league": lg}, open(OUT / "coaching.json", "w"), indent=1, default=float)
print(json.dumps(lg, indent=1, default=float))
print(json.dumps(plan["PHI"], indent=1, default=float)[:3000])
