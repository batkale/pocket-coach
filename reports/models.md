# Level 3 expected-rep model

Target: closest distance (yds) the blocker's rusher gets to the QB within 2.5 s of the snap.
5-fold split by game. Reps: 45926.

| model | held-out MAE (yds) |
|---|---|
| league mean | 1.024 |
| situational average (slot x rushers x play action) | 0.985 |
| gradient boosting | 0.969 |

Flag rule: residual > 2.0 sd (2.39 yds), rusher within 3.0 yds of QB, and no PFF label on that rep. Flags: 387.
