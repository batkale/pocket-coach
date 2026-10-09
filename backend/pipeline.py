"""Pass Protection Error Finder - offline pipeline.

Reads the Big Data Bowl 2023 data + nflverse EPA, resolves snap / end-of-dropback frames,
normalizes direction, detects Level 1 (Confirmed) and Level 2 (Likely) flags, attaches
shared EPA cost, builds Wilson-interval patterns, and writes JSON for the static frontend.

Usage: python backend/pipeline.py
"""
import glob, hashlib, json, math, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from pathlib import Path
import numpy as np, pandas as pd, yaml

ROOT = Path(__file__).resolve().parents[1]
RAW = Path(os.environ.get("NFL_RAW", ROOT / "nfl-big-data-bowl-regional-event-data-main" / "data"))
OUT = ROOT / "frontend"
CFG = yaml.safe_load(open(ROOT / "config" / "thresholds.yaml"))
L = CFG["field"]["length_yd"]; W = CFG["field"]["width_yd"]; HZ = CFG["field"]["frame_rate_hz"]
ENG_D = CFG["engagement"]["distance_yd"]; ENG_N = CFG["engagement"]["min_consecutive_frames"]
FREE_QB = CFG["level2"]["free_rusher_qb_yd"]; EXCL = set(CFG["level2"]["excluded_block_types"])

from geometry import flip_dir, resolve_play_frames, first_run, wilson


def normalize(t):
    """Offense always moves toward increasing x."""
    left = t.playDirection == "left"
    t.loc[left, "x"] = L - t.loc[left, "x"]
    t.loc[left, "y"] = W - t.loc[left, "y"]
    for c in ("o", "dir"):
        t.loc[left, c] = flip_dir(t.loc[left, c])
    return t


# ---------------------------------------------------------------- load
games = pd.read_csv(RAW / "games.csv")
plays = pd.read_csv(RAW / "plays.csv")
players = pd.read_csv(RAW / "players.csv").set_index("nflId")
pff = pd.read_csv(RAW / "pffScoutingData.csv")
plays = plays.merge(games[["gameId", "week", "homeTeamAbbr", "visitorTeamAbbr"]], on="gameId")
playIdx = plays.set_index(["gameId", "playId"])

try:
    pbp = pd.read_parquet(ROOT / "ext" / "pbp_2021.parquet", columns=["old_game_id", "play_id", "epa"])
    pbp = pbp.dropna(subset=["play_id"])
    epa = {(int(g), int(p)): e for g, p, e in zip(pbp.old_game_id, pbp.play_id, pbp.epa)}
except Exception as ex:  # offline: flags still produced, cost unavailable
    print("EPA unavailable:", ex); epa = {}

flags, unresolved, events_seen, last_events, play_json = [], [], set(), {}, {}
blockReps = []  # (nflId, team, gameId, playId, down, distBand) opportunities for blocker patterns


def dist_band(ytg):
    a, b = CFG["patterns"]["distance_bands"]
    return "short" if ytg <= a else ("medium" if ytg <= b else "long")


def add_flag(gid, pid, frame, ids, team, etype, level, expl, detail):
    fid = hashlib.md5(f"{gid}-{pid}-{etype}-{sorted(ids)}".encode()).hexdigest()[:12]
    flags.append(dict(flagId=fid, gameId=gid, playId=pid, errorFrameId=int(frame), involvedNflIds=[int(i) for i in ids],
                      team=team, errorType=etype, confidenceLevel=level, explanation=expl, detail=detail))


def pname(i):
    return players.displayName.get(i, str(i))


def ppos(i):
    return players.officialPosition.get(i, "")


# ---------------------------------------------------------------- per game
files = sorted(glob.glob(str(RAW / "tracking" / "*.csv")))[:int(os.environ.get("NFL_LIMIT", 999))]
for fi, f in enumerate(files):
    t = normalize(pd.read_csv(f))
    gid = int(t.gameId.iloc[0])
    events_seen |= set(t.event.dropna().unique())
    gp = pff[pff.gameId == gid]
    for pid, p in t.groupby("playId"):
        if (gid, pid) not in playIdx.index: continue
        pl = playIdx.loc[(gid, pid)]
        evs = p[p.event != "None"][["frameId", "event"]].drop_duplicates()
        if len(evs): last_events[evs.event.iloc[-1]] = last_events.get(evs.event.iloc[-1], 0) + 1
        snap, end, ok, why = resolve_play_frames(evs)
        if not ok:
            unresolved.append((gid, pid, why)); continue
        off, dfn = pl.possessionTeam, pl.defensiveTeam
        r = gp[gp.playId == pid].set_index("nflId")
        role = r.pff_role
        qb = role.index[role == "Pass"]
        if len(qb) == 0:
            unresolved.append((gid, pid, "no QB")); continue
        qb = qb[0]
        win = p[p.frameId.between(snap, end) & p.nflId.notna()]
        X = win.pivot(index="frameId", columns="nflId", values="x")
        Y = win.pivot(index="frameId", columns="nflId", values="y")
        if qb not in X: continue
        frames = X.index.to_numpy()
        blockers = [i for i in role.index[role == "Pass Block"] if i in X]
        rushers = [i for i in role.index[role == "Pass Rush"] if i in X]
        dq = {i: np.hypot(X[i] - X[qb], Y[i] - Y[qb]).to_numpy() for i in rushers + blockers}
        closest = {i: int(frames[np.nanargmin(dq[i])]) for i in rushers}
        new = []

        # --- Level 1: PFF-recorded protection errors
        for b in blockers:
            br = r.loc[b]
            blockReps.append((b, off, gid, pid, int(pl.down), dist_band(pl.yardsToGo)))
            tgt = br.pff_nflIdBlockedPlayer
            if pd.isna(tgt) or int(tgt) not in dq:
                # engaged rusher = rusher closest to this blocker over the dropback
                cand = [(np.nanmin(np.hypot(X[i] - X[b], Y[i] - Y[b])), i) for i in rushers]
                tgt = min(cand)[1] if cand else None
            tgt = int(tgt) if tgt is not None else None
            for col, et, word in [("pff_sackAllowed", "sack_allowed", "a sack"), ("pff_hitAllowed", "hit_allowed", "a QB hit"),
                                  ("pff_hurryAllowed", "hurry_allowed", "a QB hurry")]:
                if br[col] == 1 and tgt is not None:
                    new.append((closest[tgt], [b, tgt], off, et, "Confirmed",
                                f"{pname(b)} ({ppos(b)}) allowed {word} by {pname(tgt)}.", {"source": "pff", "label": col}))
            if br.pff_beatenByDefender == 1 and tgt is not None:
                passed = np.where(dq[tgt] < dq[b])[0]
                fr = int(frames[passed[0]]) if len(passed) else closest[tgt]
                new.append((fr, [b, tgt], off, "beaten", "Confirmed",
                            f"{pname(b)} ({ppos(b)}) was beaten by {pname(tgt)}.",
                            {"source": "pff", "label": "pff_beatenByDefender", "passFrameFound": bool(len(passed))}))

        # --- Level 1: penalties (error moment = snap)
        teams = p.drop_duplicates("nflId").set_index("nflId").team
        for k in (1, 2, 3):
            fn, fid = pl[f"foulName{k}"], pl[f"foulNFLId{k}"]
            if pd.notna(fn) and pd.notna(fid) and int(fid) in teams.index:
                new.append((snap, [int(fid)], teams[int(fid)], "penalty", "Confirmed",
                            f"{pname(int(fid))} ({ppos(int(fid))}) was flagged for {fn}.", {"source": "penalty", "foulName": fn}))

        # --- Level 2: free rusher (protection had enough blockers but someone came clean)
        counted = [b for b in blockers if r.loc[b].pff_blockType not in EXCL]
        if blockers and rushers and len(counted) >= len(rushers):
            for ru in rushers:
                near = np.nanmin(np.vstack([np.hypot(X[b] - X[ru], Y[b] - Y[ru]).to_numpy() for b in blockers]), axis=0)
                close = np.where(dq[ru] <= FREE_QB)[0]
                if not len(close): continue
                eng = first_run(near[:close[0] + 1] <= ENG_D, ENG_N)
                if eng >= 0: continue
                line = X[blockers].mean(axis=1).to_numpy()
                crossed = np.where(X[ru].to_numpy() < line)[0]
                fr = int(frames[crossed[0]]) if len(crossed) else int(frames[close[0]])
                i = int(frames.searchsorted(fr))
                nb = min(blockers, key=lambda b: math.hypot(X[b].iloc[i] - X[ru].iloc[i], Y[b].iloc[i] - Y[ru].iloc[i]))
                pressured = bool((r.loc[ru][["pff_hit", "pff_hurry", "pff_sack"]] == 1).any())
                new.append((fr, [ru, nb], off, "free_rusher", "Likely",
                            f"Likely: check the film - {pname(ru)} came free with {len(counted)} blockers vs {len(rushers)} rushers; nearest blocker {pname(nb)} ({ppos(nb)}).",
                            {"rule": "free_rusher", "lineCrossFound": bool(len(crossed)), "pffPressure": pressured}))

        if not new: continue
        e = epa.get((gid, int(pid)))
        for fr, ids, team, et, lvl, ex, det in new:
            teamEpa = None if e is None or pd.isna(e) else (e if team == off else -e)
            det["epaCost"] = None if teamEpa is None else round(teamEpa / len(new), 3)
            add_flag(gid, int(pid), fr, ids, team, et, lvl, ex, det)

        # --- replay JSON for flagged plays (normalized coords, single play only)
        lo = max(int(p.frameId.min()), snap - CFG["viewer"]["pre_snap_frames"])
        v = p[p.frameId >= lo]
        objs = v.drop_duplicates("nflId")
        ids = [None if pd.isna(i) else int(i) for i in objs.nflId]
        meta = [{"id": i, "jersey": None if i is None else int(j), "team": tm,
                 "role": None if i is None else role.get(i), "align": None if i is None else r.pff_positionLinedUp.get(i),
                 "name": "ball" if i is None else pname(i), "pos": "" if i is None else ppos(i)}
                for i, j, tm in zip(ids, objs.jerseyNumber, objs.team)]
        key = lambda s: -1 if pd.isna(s) else int(s)
        vx = v.assign(k=v.nflId.map(key)).pivot(index="frameId", columns="k", values="x")
        vy = v.assign(k=v.nflId.map(key)).pivot(index="frameId", columns="k", values="y")
        cols = [-1 if i is None else i for i in ids]
        fev = v.drop_duplicates("frameId").set_index("frameId").event
        play_json[f"{gid}_{pid}"] = {
            "header": {"gameId": gid, "playId": int(pid), "offense": off, "defense": dfn, "quarter": int(pl.quarter),
                       "clock": pl.gameClock, "down": int(pl.down), "yardsToGo": int(pl.yardsToGo), "result": pl.passResult,
                       "coverage": None if pd.isna(pl.pff_passCoverage) else pl.pff_passCoverage, "desc": pl.playDescription, "week": int(pl.week)},
            "meta": {"snap": snap, "end": end, "los": float(p[(p.frameId == snap) & p.nflId.isna()].x.iloc[0]),
                     "firstDown": float(p[(p.frameId == snap) & p.nflId.isna()].x.iloc[0]) + int(pl.yardsToGo), "qb": int(qb)},
            "players": meta, "frameIds": [int(x) for x in vx.index],
            "events": {int(k): ev for k, ev in fev.items() if pd.notna(ev) and ev != "None"},
            "x": [[None if pd.isna(a) else round(float(a), 2) for a in vx[c]] for c in cols],
            "y": [[None if pd.isna(a) else round(float(a), 2) for a in vy[c]] for c in cols],
        }
    print(f"[{fi + 1}/{len(files)}] {gid}: {len(flags)} flags", flush=True)

# ---------------------------------------------------------------- outputs
fl = pd.DataFrame(flags)
fl["primary"] = fl.involvedNflIds.str[0]
fl["primaryName"] = fl.primary.map(pname); fl["primaryPos"] = fl.primary.map(ppos)
fl = fl.merge(plays[["gameId", "playId", "week", "down", "yardsToGo", "possessionTeam", "defensiveTeam"]], on=["gameId", "playId"])
fl["epaCost"] = fl.detail.map(lambda d: d.get("epaCost"))
assert ((fl.errorFrameId >= 1)).all()

# patterns: player x error type x down x distance band; opportunities = that player's pass-block reps there
reps = pd.DataFrame(blockReps, columns=["nflId", "team", "gameId", "playId", "down", "band"])
opp = reps.groupby(["nflId", "team", "down", "band"]).size().rename("opportunities")
fl["band"] = fl.yardsToGo.map(dist_band)
pf = fl[fl.errorType != "penalty"]
pt = pf.groupby(["primary", "team", "errorType", "down", "band"]).agg(
    count=("flagId", "size"), avgCost=("epaCost", "mean"),
    plays=("playId", lambda s: [f"{g}_{p}" for g, p in zip(pf.loc[s.index, "gameId"], s)])).reset_index()
pt = pt.join(opp, on=["primary", "team", "down", "band"]).dropna(subset=["opportunities"])
pt = pt[pt.opportunities >= CFG["patterns"]["min_opportunities"]]
pt["rate"] = pt["count"] / pt.opportunities
ci = [wilson(int(k), int(n), CFG["patterns"]["interval_confidence"]) for k, n in zip(pt["count"], pt.opportunities)]
pt["rateLow90"] = [a for a, b in ci]; pt["rateHigh90"] = [b for a, b in ci]
# rank by frequency x average cost (cost from charged team's view is negative when bad), count if cost missing
pt["rankScore"] = np.where(pt.avgCost.notna(), pt["count"] * -pt.avgCost.fillna(0), pt["count"])
pt["name"] = pt.primary.map(pname); pt["pos"] = pt.primary.map(ppos)
pt = pt.sort_values("rankScore", ascending=False)

OUT.mkdir(exist_ok=True); (OUT / "plays").mkdir(exist_ok=True)
for k, v in play_json.items():
    json.dump(v, open(OUT / "plays" / f"{k}.json", "w"), separators=(",", ":"))
json.dump({"flags": json.loads(fl.drop(columns=["band"]).to_json(orient="records")),
           "patterns": json.loads(pt.to_json(orient="records")),
           "teams": sorted(set(games.homeTeamAbbr) | set(games.visitorTeamAbbr)),
           "games": json.loads(games.to_json(orient="records"))},
          open(OUT / "data.json", "w"), separators=(",", ":"))

# reports
os.makedirs(ROOT / "reports", exist_ok=True)
with open(ROOT / "reports" / "data_check.md", "w") as fh:
    fh.write("# Data check\n\n")
    fh.write(f"- Tracking files: {len(files)}; plays in plays.csv: {len(plays)}\n")
    fh.write(f"- Distinct events: {', '.join(sorted(events_seen))}\n")
    fh.write("- Last event per play (counts): " + ", ".join(f"{k}={v}" for k, v in sorted(last_events.items(), key=lambda x: -x[1])) + "\n")
    fh.write("- Tracking ends ~0.5 s after the throw on pass plays (no catch / tackle frames).\n")
    for c in ["pff_nflIdBlockedPlayer", "pff_positionLinedUp"]:
        fh.write(f"- Missing {c} (Pass Block rows): {pff[pff.pff_role == 'Pass Block'][c].isna().mean():.1%}\n")
    fh.write(f"\n## Unresolved plays ({len(unresolved)})\n\n| gameId | playId | reason |\n|---|---|---|\n")
    for g, p_, why in unresolved: fh.write(f"| {g} | {p_} | {why} |\n")

fr_ = fl[fl.errorType == "free_rusher"]
prec = fr_.detail.map(lambda d: d["pffPressure"]).mean() if len(fr_) else float("nan")
with open(ROOT / "reports" / "level2_calibration.md", "w") as fh:
    fh.write("# Level 2 calibration\n\n| rule | flags | precision vs PFF pressure label |\n|---|---|---|\n")
    fh.write(f"| free_rusher | {len(fr_)} | {prec:.1%} (share of flagged rushers PFF credits with a hit/hurry/sack) |\n")
print(fl.groupby(["confidenceLevel", "errorType"]).size())
print("patterns:", len(pt), "| replay files:", len(play_json), "| unresolved:", len(unresolved), "| free-rusher precision:", round(prec, 3))
