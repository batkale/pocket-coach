"""Receiver 'Earned Value': expected EPA a receiver offered on every route,
targeted or not, vs the value the QB actually delivered to them."""
import pandas as pd, numpy as np
f = pd.read_parquet("scored.parquet").dropna(subset=["xEPA"])
f = f[f.officialPosition.isin(["WR", "TE", "RB"])]
p = f.groupby(["gameId", "playId"])
f["best"] = p.xEPA.transform("max")
f["is_best"] = f.xEPA == f.best
f["tgt_x"] = p.xEPA.transform(lambda s: s[f.loc[s.index, "targeted"]].max())
play = f.groupby(["gameId", "playId"]).agg(best=("xEPA", "max"), tgt=("tgt_x", "first"), any_t=("targeted", "any"))
play = play[play.any_t]
print("throws to model's best option:", f[f.targeted].is_best.mean().round(3))
print("mean EPA left on table per dropback:", (play.best - play.tgt).mean().round(3))

f["ignored_open"] = f.is_best & ~f.targeted & ((f.best - f.tgt_x) > 0.5)
lb = f.groupby(["displayName", "officialPosition", "possessionTeam"]).agg(
    routes=("xEPA", "size"), xEPA_route=("xEPA", "mean"), best_rate=("is_best", "mean"),
    targets=("targeted", "sum"), ignored=("ignored_open", "sum"),
    act_epa=("epa", lambda s: s[f.loc[s.index, "targeted"]].sum())).query("routes>=120")
lb["tgt_rate"] = lb.targets / lb.routes
lb["act_epa_per_tgt"] = lb.act_epa / lb.targets
lb = lb.sort_values("xEPA_route", ascending=False)
pd.set_option("display.width", 200)
print(lb.round(3).head(15)); print(lb.round(3).tail(8))
print("most ignored:\n", (lb.ignored / lb.routes).sort_values(ascending=False).head(10).round(3))
print(lb[["xEPA_route", "tgt_rate", "act_epa_per_tgt"]].corr().round(2))
lb.to_csv("leaderboard.csv")
