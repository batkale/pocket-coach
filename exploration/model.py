"""Expected value of every route: train on actual targets, score every route runner
(including the ones the QB ignored). Out-of-fold by game to avoid leakage."""
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.model_selection import GroupKFold
from sklearn.metrics import roc_auc_score, brier_score_loss

f = pd.read_parquet("features.parquet")
f["man"] = (f.pff_passCoverageType == "Man").astype(int)
X_COLS = ["sep", "sep2", "def_within5", "def_speed", "speed", "depth", "throw_dist", "sideline_dist",
          "t_throw", "man", "down", "yardsToGo", "yardline_100"]
tr = f[f.targeted & f.passResult.isin(["C", "I", "IN"]) & f.epa.notna()].copy()
tr["comp"] = (tr.passResult == "C").astype(int)

f["xComp"] = np.nan; f["xEPA"] = np.nan
oof_c = np.zeros(len(tr)); oof_e = np.zeros(len(tr))
for k, (a, b) in enumerate(GroupKFold(5).split(tr, groups=tr.gameId)):
    ga = tr.gameId.iloc[a].unique()
    clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_depth=4).fit(tr[X_COLS].iloc[a], tr.comp.iloc[a])
    reg = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_depth=4, l2_regularization=1.0, min_samples_leaf=40).fit(tr[X_COLS].iloc[a], tr.epa.iloc[a])
    oof_c[b] = clf.predict_proba(tr[X_COLS].iloc[b])[:, 1]; oof_e[b] = reg.predict(tr[X_COLS].iloc[b])
    held = ~f.gameId.isin(ga)  # score all route runners in held-out games
    f.loc[held, "xComp"] = clf.predict_proba(f.loc[held, X_COLS])[:, 1]
    f.loc[held, "xEPA"] = reg.predict(f.loc[held, X_COLS])

print(f"xComp AUC {roc_auc_score(tr.comp, oof_c):.3f} | Brier {brier_score_loss(tr.comp, oof_c):.3f}")
ok = tr.cp.notna()
print(f"nflverse cp (no tracking) AUC {roc_auc_score(tr.comp[ok], tr.cp[ok]):.3f} | Brier {brier_score_loss(tr.comp[ok], tr.cp[ok]):.3f}")
print(f"xEPA corr w/ actual EPA {np.corrcoef(oof_e, tr.epa)[0,1]:.3f}")
f.to_parquet("scored.parquet")
