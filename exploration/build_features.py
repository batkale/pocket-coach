"""Snapshot every route runner at the moment of the throw (Next Gen Stats tracking),
then attach play outcomes from nflverse play-by-play (EPA, air yards, YAC)."""
import glob
import numpy as np, pandas as pd

D = "../nfl-big-data-bowl-regional-event-data-main/data/"
plays = pd.read_csv(D + "plays.csv")
players = pd.read_csv(D + "players.csv")
pff = pd.read_csv(D + "pffScoutingData.csv")
routes = pff[pff.pff_role == "Pass Route"][["gameId", "playId", "nflId", "pff_positionLinedUp"]]

rows = []
for f in sorted(glob.glob(D + "tracking/*.csv")):
    t = pd.read_csv(f, usecols=["gameId", "playId", "nflId", "frameId", "team", "x", "y", "s", "event", "playDirection"])
    ev = t[t.event.isin(["ball_snap", "autoevent_ballsnap", "pass_forward", "autoevent_passforward"])]
    ev = ev.assign(kind=np.where(ev.event.str.contains("snap"), "snap", "throw"))
    key = ev.groupby(["playId", "kind"]).frameId.min().unstack()
    if "throw" not in key or "snap" not in key: continue
    gid = t.gameId.iloc[0]
    pl = plays[plays.gameId == gid].set_index("playId")
    for pid, (snap, throw) in key[["snap", "throw"]].dropna().iterrows():
        if pid not in pl.index: continue
        p = t[t.playId == pid]
        off = pl.at[pid, "possessionTeam"]
        sgn = 1 if p.playDirection.iloc[0] == "right" else -1
        ball0 = p[(p.frameId == snap) & p.nflId.isna()]
        fr = p[(p.frameId == throw)]
        ball = fr[fr.nflId.isna()]
        fr = fr[fr.nflId.notna()]
        o, d = fr[fr.team == off], fr[fr.team != off]
        if d.empty or o.empty or ball0.empty or ball.empty: continue
        los, bx, by = ball0.x.iloc[0], ball.x.iloc[0], ball.y.iloc[0]
        dxy, ds = d[["x", "y"]].to_numpy(), d.s.to_numpy()
        for r in o.itertuples():
            dist = np.hypot(dxy[:, 0] - r.x, dxy[:, 1] - r.y)
            srt = np.sort(dist)
            rows.append((gid, pid, int(r.nflId), srt[0], srt[:2].mean(), (dist < 5).sum(), ds[dist.argmin()],
                         r.s, (r.x - los) * sgn, np.hypot(r.x - bx, r.y - by), min(r.y, 53.3 - r.y),
                         (throw - snap) / 10))
    print(f[-25:], len(rows), flush=True)

cols = ["gameId", "playId", "nflId", "sep", "sep2", "def_within5", "def_speed", "speed", "depth",
        "throw_dist", "sideline_dist", "t_throw"]
feat = pd.DataFrame(rows, columns=cols)
feat = feat.merge(routes, on=["gameId", "playId", "nflId"])  # route runners only
feat = feat.merge(players[["nflId", "displayName", "officialPosition"]], on="nflId")
feat = feat.merge(plays[["gameId", "playId", "possessionTeam", "passResult", "pff_passCoverageType",
                         "down", "yardsToGo", "absoluteYardlineNumber"]], on=["gameId", "playId"])

# nflverse play-by-play: outcome + intended receiver
pbp = pd.read_parquet("../ext/pbp_2021.parquet",
                      columns=["old_game_id", "play_id", "epa", "air_yards", "yards_after_catch", "cp",
                               "complete_pass", "receiver_player_name", "passer_player_name", "yardline_100"])
pbp = pbp.rename(columns={"old_game_id": "gameId", "play_id": "playId"})
pbp["gameId"] = pbp.gameId.astype(int); pbp["playId"] = pbp.playId.astype(int)
feat = feat.merge(pbp, on=["gameId", "playId"], how="left")

def short(n):
    p = n.replace("Jr.", "").replace("II", "").split()
    return f"{p[0][0]}.{p[-1]}" if len(p) > 1 else n
feat["targeted"] = feat.displayName.map(short) == feat.receiver_player_name
feat.to_parquet("features.parquet")
g = feat.groupby(["gameId", "playId"])
print(feat.shape, "plays:", g.ngroups, "with matched target:", g.targeted.any().mean())
