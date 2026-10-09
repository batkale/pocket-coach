"""Coverage breakdowns: for each route runner, find the defender matched to him 1.0s after
the snap, then follow their distance frame by frame until the throw."""
import glob
import numpy as np, pandas as pd

D = "../nfl-big-data-bowl-regional-event-data-main/data/"
plays = pd.read_csv(D + "plays.csv").set_index(["gameId", "playId"])
pff = pd.read_csv(D + "pffScoutingData.csv")
role = pff.set_index(["gameId", "playId", "nflId"]).pff_role

rows = []
for f in sorted(glob.glob(D + "tracking/*.csv")):
    t = pd.read_csv(f, usecols=["gameId", "playId", "nflId", "frameId", "team", "x", "y", "event"])
    gid = t.gameId.iloc[0]
    ev = t[t.event.isin(["ball_snap", "autoevent_ballsnap", "pass_forward", "autoevent_passforward"])]
    ev = ev.assign(kind=np.where(ev.event.str.contains("snap"), "snap", "throw"))
    key = ev.groupby(["playId", "kind"]).frameId.min().unstack()
    if "throw" not in key or "snap" not in key: continue
    for pid, (snap, throw) in key[["snap", "throw"]].dropna().astype(int).iterrows():
        if (gid, pid) not in plays.index or throw - snap < 15: continue
        p = t[(t.playId == pid) & t.nflId.notna() & t.frameId.between(snap, throw)]
        r = role.reindex(list(zip(p.gameId, p.playId, p.nflId)))
        p = p.assign(role=r.to_numpy())
        X = p.pivot(index="frameId", columns="nflId", values="x"); Y = p.pivot(index="frameId", columns="nflId", values="y")
        ids = p.drop_duplicates("nflId").set_index("nflId").role
        rec, dfn = ids[ids == "Pass Route"].index, ids[ids == "Coverage"].index
        if len(rec) == 0 or len(dfn) == 0: continue
        m = snap + 10
        for rid in rec:
            d = np.hypot(X[dfn].sub(X[rid], axis=0), Y[dfn].sub(Y[rid], axis=0))  # frames x defenders
            did = d.loc[m].idxmin()
            tl = d[did].to_numpy()
            after = tl[10:]
            lost = np.argmax(after > 3.0) if (after > 3.0).any() else -1
            rows.append((gid, pid, int(rid), int(did), tl[10], tl.min(), tl[-1], d.iloc[-1].min(),
                         int(d.iloc[-1].idxmin()), (lost + 10) / 10 if lost >= 0 else np.nan, (throw - snap) / 10))
    print(f[-25:], len(rows), flush=True)

cov = pd.DataFrame(rows, columns=["gameId", "playId", "nflId", "def_matched", "gap_1s", "gap_min", "gap_throw",
                                  "nearest_throw", "def_nearest_throw", "t_lost", "t_throw"])
cov.to_parquet("coverage.parquet")
print(cov.describe().round(2))
