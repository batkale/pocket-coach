# PocketWatch

**The insight:** coaches can't see every protection breakdown live, so PocketWatch combines Next Gen Stats tracking, PFF charting and nflverse EPA to flag every pass-protection error in Weeks 1-8 of 2021 (**8,472 flags across 122 games**), each linked to an animated replay that zooms in on the error moment. Flags are grouped into three levels by how sure we are: **Level 1 Confirmed** (charted by PFF or a penalty), **Level 2 Likely** (our tracking rule) and **Level 3 Possible** (our model). A **Game Plan** tab compares each team with the league and turns its biggest gaps into what to tell the players, a scheme fix and film to show them, or, in opponent mode, how to attack them. The headline skill-position finding: **running backs allow pressure on 11.3% of their pass-block reps (n=1,554), more than tight ends (8.6%), tackles (7.4%), guards (5.9%) or centres (4.2%)**, so the RB is the weakest link in protection. League-wide, protection breaks down on **55% of 3rd-and-long dropbacks vs 42% on early downs**, and play action cuts breakdowns from 47% to 37%.

![viewer](docs/viewer.png)

## Run it

```bash
pip install -r requirements.txt
make data   # downloads nflverse 2021 play-by-play (cached in ext/), runs backend/pipeline.py then backend/coaching.py
make dev    # http://localhost:8000
make test   # unit tests: geometry, convex-hull pocket area, snap/throw resolver, engagement runs, Wilson bounds
```

The pipeline expects the competition data at `nfl-big-data-bowl-regional-event-data-main/data/` (or set `NFL_RAW`). Pre-built outputs are committed in `frontend/` (`data.json`, `coaching.json`, `teams.json`, logos and one replay JSON per flagged play), so `make dev` works without re-running the pipeline.

## The three levels

| Level | How it is found | Flags | Label in the app |
|---|---|---|---|
| **1 · Confirmed** | Recorded in the data: PFF sack, hit or hurry allowed, beaten by defender, or a penalty. No modelling. | 5,675 | Confirmed |
| **2 · Likely** | Tracking rule: a rusher reaches 3 yds of the QB without being engaged (1.5 yds for 3+ frames) even though the offense had at least as many blockers as rushers. Chip, set-and-release and no-block assignments don't count as blockers. | 2,410 | Likely: check the film |
| **3 · Possible** | Expected-rep model: for all 45,926 pass-block reps we measure how close the blocker's rusher got to the QB in the first 2.5 s, predict what is normal for that situation (alignment, rushers, blockers, down, distance, play action, dropback type), and flag reps where the rusher got more than 2 SD closer than expected, came within 3 yds of the QB, and PFF charted nothing. | 387 | Possible: film to review |

Each flag records the error moment (the frame the replay opens on): the rusher's closest approach to the QB for pressures, the frame he passes the blocker for beats, the snap for penalties, and the line-of-blockers crossing for free rushers.

**How much each error cost.** Each flag carries the play's EPA (expected points added, from nflverse), seen from the team that made the error and split equally across all flags on that play. The app shows it in plain words: a severity badge (**Drive-killer** 3+ points, **Costly** 1 to 3, **Minor** under 1, **Survived** if the play still gained), "Cost about X points", and what happened on the play ("Sack, lost 8 yds", "Interception").

## The Game Plan

`backend/coaching.py` uses **Level 1 flags only**, so every coaching point rests on charted data. For each team it compares the share of dropbacks with a protection breakdown against the league in five areas:

- **Rush size:** 4 or fewer rushers, 5-man pressure, 6+ man blitz
- **Situation:** 1st/2nd down, 3rd/4th and short, 3rd/4th and long
- **Play type:** play action vs straight dropback
- **Who lost:** left and right tackle, left and right guard, centre, running back, tight end (per pass-block rep)
- **Timing:** breakdowns under 2.5 s after the snap (technique and assignment) vs over 3.5 s (QB holding the ball)

A situation becomes a finding when the team is at least 4 percentage points worse than the league with 15 or more dropbacks or reps. It is tagged **Strong signal** when the 90% Wilson interval sits fully above the league rate (22 of 32 teams have at least one), otherwise **Trend**. Each finding shows:

- **My team mode:** what to tell the players, the tactic or scheme fix, the players to coach (with counts), and three film clips
- **Opponent mode:** how to attack it, for example "Put your best edge rusher over their right tackle"
- **Keep doing / avoid attacking here:** the team's biggest strengths

League-wide lessons shown on every team's plan:

| Pattern | Number | What to do |
|---|---|---|
| 3rd/4th and 7+ | 55% breakdown rate vs 42% on early downs | Max protection, screens and draws on obvious passing downs |
| Play action | 37% vs 47% on straight dropbacks | Use play action to buy the QB time |
| Running backs | 16% of pass-block reps lose, more than any lineman (centre 7%) | Chip and release instead of leaving the back alone in pickup |
| Timing | 43% of breakdowns happen inside 2.5 s | Most breakdowns are technique, not the QB holding the ball |

## How it works

- `backend/pipeline.py`: resolves the snap and end-of-dropback frames (manual events first, then auto events), flips plays so the offense always moves toward +x, detects Level 1, 2 and 3 flags, attaches the shared EPA cost, builds player patterns, and writes the replay JSON.
- `backend/coaching.py`: builds the Game Plan (`frontend/coaching.json`).
- **Patterns:** grouped by player × error × down × distance band. The denominator is that player's pass-block reps in that situation, with 90% Wilson intervals. Patterns with fewer than 10 opportunities are hidden.
- All thresholds live in `config/thresholds.yaml`. Reports are in `reports/`: data check, Level 2 calibration, Level 3 model.
- `frontend/index.html`: a static HTML Canvas app with the Game Plan, alerts grouped by level, patterns, weak links and the play viewer. The viewer zooms on the error, fades uninvolved players, labels the blocker, rusher and QB, uses team colours and logos, and has 0.25/0.5/1x speeds, a scrubber, arrow keys and click-a-player details.

## Limitations

- The play call is unknown, so an error may be the protection design rather than the player.
- Only pass plays are covered, and tracking ends about 0.5 s after the throw.
- Eight weeks of data gives small samples. The app always shows sample sizes and intervals.
- The Level 2 free-rusher rule matches a PFF pressure on the same rusher only 16.7% of the time.
- The Level 3 model is weak: average error 0.97 yds, vs 0.99 for a situational average and 1.02 for the league mean (see `reports/models.md`).
- That's why Levels 2 and 3 are labelled "check the film" and not presented as fact.

*Built at the NFL Big Data Bowl London regional (UCL BaseKX, 9 Oct 2026). Data: NFL Next Gen Stats, PFF, nflverse. Team colours and logo URLs from nflverse `teams_colors_logos`; logos are trademarks of their teams, used here for identification only.*
