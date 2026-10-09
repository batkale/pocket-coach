# Design Document

## Overview

The Pass Protection Error Finder is a monorepo web application that ingests the NFL Big Data Bowl 2023 tracking data (2021 season, Weeks 1-8, 122 games), converts it once into columnar Parquet, derives direction-independent geometric measurements, runs a three-level detection engine, groups the resulting flags into ranked patterns, attaches an expected-points cost from nflverse EPA, and serves everything to a React canvas-based film viewer.

The architecture is a one-time offline data pipeline (`make data`) that writes processed Parquet tables, plus a long-running FastAPI service (`make dev`) that queries those tables through DuckDB and returns only per-play slices to a React + TypeScript + Vite frontend. The pipeline never loads the raw CSVs per request, and the API never loads a whole game into memory — it returns per-play frame data only (Requirement 2.5, 1.2).

Every detected error is a `Flag` carrying a resolvable error-moment frame within the play's frame range, so each flag can always open a working animated replay. A flag without a working replay is not considered complete (Introduction, Requirement 13). The `Flag` schema is deliberately stable and self-describing so a future broadcaster mode can reuse detection outputs unchanged (Requirement 16.4); broadcaster mode itself is out of scope.

The whole tool is scoped to a selected my-team and opponent: the user picks a **my-team abbreviation** and an **opponent abbreviation**, both drawn from `games.csv`, and the URL stores `myTeam`, `opponent`, and `mode`. In the default **self** mode the tool shows the my-team's own errors; in **opponent** mode it shows the opponent's errors (Requirement 10.1-10.3).

### Technology Decisions (confirmed)

- **Monorepo** at workspace root: `backend/` (Python 3.11+), `frontend/` (React + TS + Vite). Raw CSVs move from `data/` into `data/raw/`; processed Parquet lands in `data/processed/`. Trained models are versioned under `models/`, metrics/reports under `reports/`, tunable numbers under `config/thresholds.yaml`. Root `make data`, `make dev`, `make test` (Requirement 1.1-1.5).
- **Data engine**: Polars for transforms, DuckDB for serving queries over Parquet (Requirement 1.6, 2.5).
- **Backend**: FastAPI serving plays, frames, flags, patterns, players as JSON.
- **Frontend**: React + TypeScript + Vite; the field is drawn on an **HTML Canvas** (not SVG) because we animate 23 objects at 10 fps; a lightweight chart library (Recharts) renders pattern screens. The selected my-team, opponent, and mode live in URL query params (Requirement 10.1, 13.9).
- **Models**: scikit-learn baseline + LightGBM GBM; train/test split **by game** (Requirement 7.6); low-rep player history shrunk toward position averages, empirical-Bayes style, below a configurable `Rep_Threshold` (Requirement 7.8); player-history features computed from training games only or leave-one-game-out so no play uses features from its own held-out game (Requirement 7.7); sample sizes always tracked and surfaced (Requirement 7.9, 14.5).
- **Cost**: nflverse play-by-play EPA auto-downloaded and locally cached; merged on `gameId→old_game_id`, `playId→play_id`; degrades gracefully offline (Requirement 8.2-8.5).

## Architecture

```
┌──────────────────────── OFFLINE PIPELINE  (make data) ──────────────────────────┐
│                                                                                  │
│  data/raw/*.csv ──► Phase 0 Data Check ──► reports/data_check.md                 │
│   (games, plays,        (events, missing-rate, snap/eod survey)                  │
│    players, pff,                                                                 │
│    tracking×122)                                                                 │
│        │                                                                         │
│        ▼                                                                         │
│  Ingest+Normalize (Polars)                                                       │
│   • CSV→Parquet (once)   • direction normalization   • LOS, time-since-snap      │
│   • PFF role/alignment join   • ball-row tagging                                 │
│        │                                                                         │
│        ▼                                                                         │
│  Feature / Geometry module  (distance, shoelace area, crossing, flip,            │
│   engagements, depth-conceded, pocket area/shrink, closest approach, get-off)    │
│        │                                                                         │
│        ├──► Detection Engine ─ L1 Confirmed (data)                               │
│        │                     ─ L2 Likely (rules)  ◄── calibrated vs L1           │
│        │                     ─ L3 Possible (expected-rep GBM + pressure model)   │
│        │                                                                         │
│        ├──► Cost Engine (nflverse EPA cache ─► merge keys)                        │
│        │                                                                         │
│        └──► Pattern Engine (group ► rate+Wilson ► rank by freq×avgCost)          │
│                                                                                  │
│   Writes:  data/processed/*.parquet   models/*.{pkl,txt}   reports/*.md          │
└──────────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼  (DuckDB over Parquet, per-play slices only)
┌──────────────────────── FastAPI service  (make dev) ────────────────────────────┐
│  GET /plays  /plays/{id}  /flags  /patterns  /players/{id}  /limitations         │
└──────────────────────────────────────────────────────────────────────────────────┘
                                     │  JSON
                                     ▼
┌──────────────────────── React + TS + Vite frontend ────────────────────────────┐
│  Team_Selector (URL mode) ─► Alerts_List ─► Patterns_Screen ─► Play_Viewer       │
│                                               └─► Player_Page   (Canvas @10fps)   │
│  "What this tool can't tell you" note reachable from every screen                │
└──────────────────────────────────────────────────────────────────────────────────┘
```

The pipeline is a directed acyclic flow: each stage reads the previous stage's Parquet output, so a review gate (Requirement 16.1) can run after any phase simply by inspecting the tables and reports written so far.

### Repository layout

```
/
├── Makefile                      # make data | make dev | make test
├── config/thresholds.yaml        # all tunable numbers + comments
├── data/
│   ├── raw/                       # games.csv, plays.csv, players.csv, pffScoutingData.csv, tracking/*.csv
│   └── processed/                 # *.parquet (see Data Model)
├── models/                        # expected_rep.{pkl}, pressure.{txt}, metadata.json
├── reports/                       # data_check.md, level2_calibration.md, models.md
├── backend/
│   ├── pipeline/                  # ingest, normalize, features, geometry, detect/, cost, patterns
│   ├── api/                       # FastAPI app, routers, serializers
│   └── tests/                     # pytest
└── frontend/
    ├── src/ (components, canvas renderer, api client, routes)
    └── src/__tests__/             # component tests
```

## Data Models

All processed tables are Parquet in `data/processed/`, partitioned by `gameId` where it helps DuckDB prune. Key tables and their key columns:

### `tracking_norm` (normalized tracking)
Row per (gameId, playId, nflId|ball, frameId). Columns: `gameId, playId, nflId, frameId, time, jerseyNumber, team, playDirection, x, y, s, a, dis, o, dir, event, isBall, timeSinceSnap, pff_role, pff_positionLinedUp`. Coordinates are normalized so offense always moves toward increasing x (Requirement 3.1, 3.4, 3.5).

### `play_features` (play-level)
Row per (gameId, playId). Columns: `gameId, playId, snapFrameId, endOfDropbackFrameId, lineOfScrimmage, firstDownX, dropBackType, passResult, timeToThrow, rusherCount, blockerCount, hadPressure, pocketAreaBySnapOffset (array), pocketShrinkRate, resolved (bool), unresolvedReason`. Drives filtering and the model features (Requirement 4.1, 4.6).

### `engagements`
Row per detected blocker↔rusher engagement. Columns: `gameId, playId, blockerNflId, rusherNflId, startFrameId, endFrameId, minDistance, pffBlockedConsistent (bool), setPointFrameId, setPointFallbackUsed (bool)`. Derived from tracking, cross-checked against `pff_nflIdBlockedPlayer` (Requirement 4.3). `setPointFallbackUsed` is true when the velocity-stop set point could not be found within 1.0 s of the snap and the 0.5 s positional fallback was used instead (Requirement 4.8, 4.9).

### `player_measurements` (per-player, per-play)
Columns: `gameId, playId, nflId, pff_positionLinedUp, getOffTime, depthConceded_1_0, depthConceded_1_5, depthConceded_2_0, depthConceded_2_5, closestApproachDist, closestApproachFrameId, rushLateralDir (inside|outside), speedAtFirstContact, crossedWithRusher (bool), timeToPressure, rusherPassedBlocker (bool), reachedQbWithin2_5s (bool)`. (Requirement 4.2, 4.4, 4.5, 4.6.) `timeToPressure` is the time from the snap frame to the first frame the rusher is within `free_rusher_qb_yd` of the QB; `rusherPassedBlocker` and `reachedQbWithin2_5s` feed the player-page win-rate-by-rush-type metric (Requirement 14.3, 14.4).

### `flags` — canonical Flag schema (stable, broadcaster-reusable)
Every flag row conforms to this schema (Requirement 8.1, 16.4):

| Column | Type | Notes |
|---|---|---|
| `flagId` | str | deterministic hash of (gameId, playId, errorType, involvedNflIds) |
| `gameId` | int64 | |
| `playId` | int64 | |
| `errorFrameId` | int | the error moment; MUST satisfy snapFrameId ≤ errorFrameId ≤ lastFrameId. Per Level 1 type: **penalty** → snap frame; **sack/hit/hurry allowed** → closest-approach frame of the engaged rusher (or the `pff_nflIdBlockedPlayer` rusher) to the QB; **beatenByDefender** → frame the rusher passes the blocker, falling back to that rusher's closest-approach frame when the pass-moment cannot be determined. Level 2 and Level 3 set it per their rule/model (e.g. line-cross frame, pressure-spike frame). |
| `involvedNflIds` | list[int] | blocker(s)/rusher(s)/penalized player |
| `team` | str | offense or defense abbrev the flag is charged to |
| `errorType` | str | e.g. `sack_allowed`, `free_rusher`, `wasted_double_team`, `stunt_not_handled`, `lost_escape_lane`, `worse_than_expected_rep`, `pressure_spike`, `penalty` |
| `confidenceLevel` | enum | `Confirmed` \| `Likely` \| `Possible` |
| `explanation` | str | one-sentence plain English |
| `epaCost` | float \| null | play EPA from the charged team's perspective (EPA sign flipped for defensive errors), shared equally across all flags on the play; null when EPA offline/unmatched (Requirement 8.2, 8.3, 8.5). The UI labels this value "play EPA (shared)" (Requirement 8.8). |
| `detail` | json | level-specific fields (see below) |

`detail` carries level-specific context without breaking the stable top-level schema:
- L1: `{source: "pff"|"penalty", label, foulName?}`
- L2: `{rule, lineCrossFrameId?, doubleTeamNflIds?, stuntRusherNflIds?}`
- L3: `{model, predicted, actual, deltaProb?, baselineExpectation?}`

### `patterns`
Columns: `patternId, team, perspective (self|opponent), nflId, errorType, situationKey (down, distanceBand, fieldZone, scoreState), alignmentKey, protectionKey (rusherCount, stunt, playAction), count, opportunities, sampleSize, rate, rateLow90, rateHigh90, avgCost, rankScore (= count×avgCost)`. `opportunities` is the number of chances for that error type in the group and equals `sampleSize`; `rate = count / opportunities` and the Wilson 90% interval is computed from `count` and `opportunities`. (Requirement 9.)

### `epa_cache`
nflverse play-by-play slice: `old_game_id, play_id, epa, wp, ...` cached locally after first download (Requirement 8.3).

## Snap and End-of-Dropback Detection

A single robust resolver function `resolve_play_frames(play_tracking) -> (snapFrameId, endOfDropbackFrameId, resolved, reason)` is the only place these frames are determined, so every downstream measurement shares one definition (Requirement 2.2, 2.3).

**Fallback precedence** (first match wins within each group):

- Snap: `ball_snap` (manual) → `autoevent_ballsnap` (automatic). Manual preferred over automatic because manual charting is the authoritative event.
- End of dropback: `pass_forward` → `autoevent_passforward` → `qb_sack` / `strip_sack` → `run` (scramble) → last frame with a recognized terminal event. Throw/pass events are preferred over sack/scramble because the dropback is considered complete at the earliest terminal action.

If no snap variant is found, or no end-of-dropback variant is found, or the resolved end precedes the resolved snap, the play is marked `resolved = false` with an `unresolvedReason`, **excluded** from feature computation and detection, and **logged** to `reports/data_check.md` with its (gameId, playId) and reason (Requirement 2.1, 2.6). Unresolved plays never produce flags, which keeps the "every flag has a resolvable error frame" invariant intact.

## Preprocessing and Normalization

Applied in `normalize.py` on the raw tracking rows, reading thresholds and field constants from `config/thresholds.yaml`.

- **Direction normalization** (only where `playDirection == "left"`, Requirement 3.1):
  - `x' = 120 - x`
  - `y' = 53.3 - y`
  - `o' = (o + 180) mod 360`
  - `dir' = (dir + 180) mod 360`
  Right-direction rows are left unchanged. The transform is involutive (applying twice is identity), which is a correctness property below.
- **Line of scrimmage** = normalized ball `x` at the snap frame (Requirement 3.2).
- **First-down line** = `lineOfScrimmage + yardsToGo` (for the viewer, Requirement 13.1).
- **Time since snap** = `(frameId - snapFrameId) / 10` seconds (10 Hz tracking, Requirement 3.3).
- **PFF join**: `pff_role` and `pff_positionLinedUp` joined onto every tracking row by `(gameId, playId, nflId)` (Requirement 3.4).
- **Ball row**: where `nflId` is NA, tag `isBall = true` and `team = "football"` (Requirement 3.5).

## Feature and Geometry Module

`geometry.py` holds pure, unit-tested primitives (Requirement 4.7); `features.py` composes them into play/player measurements.

Geometry primitives:
- **Distance**: Euclidean `sqrt((x1-x2)^2 + (y1-y2)^2)`; symmetric and non-negative.
- **Polygon area (shoelace)**: `0.5 * |Σ (x_i·y_{i+1} − x_{i+1}·y_i)|`; always non-negative (absolute value taken).
- **Convex hull**: monotone-chain hull of an unordered point set, returning the hull vertices in counter-clockwise order. Pocket area is computed by passing the hull vertices to the shoelace primitive, so the two primitives compose cleanly.
- **Segment crossing**: orientation-sign test on the two segments' endpoints; symmetric in segment order.
- **Direction flip**: `(d + 180) mod 360`; involutive.

The geometry unit tests (Requirement 4.7) cover each primitive against hand-made fixtures, including a convex-hull-area test that supplies **unordered** input points whose correct area is known and asserts the computed pocket area equals that known value regardless of input ordering.

Composed measurements:
- **Engagement detection** (Requirement 4.3): for each candidate blocker↔rusher pair, compute per-frame distance; a run of **≥ 3 consecutive frames** with distance ≤ `engagement_distance_yd` (default 1.5) is an engagement, recording `startFrameId`, `endFrameId`, `minDistance`. The derived engagement is cross-checked against `pff_nflIdBlockedPlayer` and the agreement recorded in `pffBlockedConsistent`, but the engagement itself is derived from tracking.
- **Blocker set point** (Requirement 4.8, 4.9): the velocity-stop frame — the frame within 1.0 s of the snap at which the blocker's forward velocity toward the backfield first stops (end of the kick-slide), used as the depth reference. If no clear velocity stop occurs within 1.0 s, the set point falls back to the blocker's position at `set_point_fallback_seconds` (default 0.5 s) after the snap and `setPointFallbackUsed` is recorded as true so downstream measurements know the fallback was used.
- **Depth conceded** (Requirement 4.4): signed backfield penetration of the engaged rusher relative to the blocker's set point, sampled at 1.0, 1.5, 2.0, 2.5 s after snap.
- **Pocket area and shrink rate** (Requirement 4.1): per frame, first form the **convex hull** of the pass-blocker positions together with the QB positions, then take the **shoelace area** of that hull; shrink rate is the slope of pocket area over the dropback window.
- **Closest approach** (Requirement 4.6): per rusher, the minimum distance to the QB over the play and the frame at which it occurs.
- **Get-off time** (Requirement 4.2): time at which a rusher's speed `s` first exceeds `getoff_speed_yps` (default 2.0).
- **Rush path attributes** (Requirement 4.5): inside/outside lateral direction, speed at first contact, and whether the rusher's path crossed another rusher's path (via the crossing primitive).

## Components and Interfaces

This section groups the system's components (backend pipeline stages — Detection Engine, Cost Engine, Pattern Engine) and their interfaces (the FastAPI endpoints and the frontend component tree). Each component below reads the previous stage's Parquet output and emits the canonical `Flag` schema or a processed table; the API and frontend sections define the interfaces that expose this material to the viewer.

### Detection Engine

Three components, one per confidence level, all emitting the canonical `Flag` schema.

#### Level 1 — Confirmed (data only, no modeling; Requirement 5)
Direct lookups over `plays` and `pffScoutingData`, each with a type-specific `errorFrameId`:
- `foulName*` with matching `foulNFLId*` → **penalty** flag attributed to that player, `errorFrameId = snapFrameId` (5.1).
- `pff_sackAllowed | pff_hitAllowed | pff_hurryAllowed == 1` → flag attributed to the blocker, `errorFrameId =` the closest-approach frame of the rusher the blocker was engaged with (or the rusher named by `pff_nflIdBlockedPlayer`) to the QB (5.2).
- `pff_beatenByDefender == 1` → **beaten** flag, `errorFrameId =` the frame that rusher passes the blocker; if that pass-moment cannot be determined, fall back to the rusher's closest-approach frame to the QB (5.3, 5.4).
Level 1 is the **answer key**: Level 2 and Level 3 are calibrated against it.

#### Level 2 — Likely (explicit rules; Requirement 6)
Each rule is readable code reading thresholds from `config/thresholds.yaml`, labeled "Likely: check the film":
- **Free rusher** (6.1): `blockerCount ≥ rusherCount` and a rusher reaches within `free_rusher_qb_yd` (default 3.0) of the QB, or the throw, with no engagement; error frame = the frame the rusher crosses the line of blockers.
- **Wasted double team** (6.2): two blockers engage one rusher while another rusher is free.
- **Stunt not handled** (6.3): two rushers' paths cross within `stunt_window_s` (default 2.0), no `SW` block type recorded, neither blocker switched, and a rusher ends free or causes pressure.
- **Lost escape lane** (6.4): `passResult == "R"` and, at the frame the QB crosses outside the tackle box, both edge rushers are inside the QB.

**Blocker counting** (6.6): wherever a Level 2 rule uses a blocker count (free rusher, wasted double team), it counts only pass blockers whose block type is **not** `CH`, `SR`, or `NB`, so chip, screen-release, and no-block assignments do not inflate the protection count.

Calibration (6.7): thresholds are tuned on **training games only**; each rule's precision/recall vs the Level 1 PFF labels is then reported on **held-out games only** and written to `reports/level2_calibration.md`. The **lost escape lane** rule has no PFF label that can confirm it, so the calibration report records **"no answer key"** for that rule and it is validated instead by **manual review of a sample of flagged plays** (6.8).

#### Level 3 — Possible (models; Requirement 7)
Labeled "Possible: film to review". Two models, split **by game** (7.6):

1. **Expected-rep model** (7.1, 7.2): predicts depth conceded at 1.5 s and probability of being beaten by 2.5 s per engagement, from alignments, player history, rusher/blocker counts, and down & distance. A **baseline of situational averages is established first**, then a LightGBM model. A Possible flag fires when a rep is far worse than predicted (residual beyond `rep_residual_sigma`).
2. **Pressure-probability model** (7.3, 7.4): per-frame probability the play ends in pressure, from positions and speeds of rushers, blockers, and QB, trained on PFF hit/hurry/sack labels. A **pressure spike** is a rise of at least `pressure_spike_delta` (default 0.25) **within a sliding `pressure_spike_window` of 5 frames** — not a single-frame jump; when a spike occurs, emit a flag and **attribute the spike** to the blocker nearest the causing rusher.

**No-leakage player history** (7.7): player-history features for the Level 3 models are computed from **training games only** (or by leave-one-game-out), so no feature for a play ever uses data derived from that play's own held-out game. Low-rep players have their history **shrunk toward position averages** below `Rep_Threshold` (7.8). Rep counts are tracked; no player stat is surfaced without its sample size (7.9). Held-out metrics — AUC + calibration plot for pressure, error for depth — are written to `reports/models.md` (7.10). The models are calibrated and sanity-checked against Level 1 as the answer key.

### Cost Engine (Requirement 8)
- Auto-downloads nflverse play-by-play EPA, caches to `data/processed/epa_cache.parquet` (8.4).
- Merges each flag's `(gameId, playId)` to nflverse `(old_game_id, play_id)` (8.7).
- **Team perspective** (8.2): cost is expressed from the perspective of the team charged with the flag, flipping the EPA sign for defensive errors (so a defensive error that cost the offense points reads as a positive charge against the defense).
- **Equal split** (8.3): when a play carries k flags, the play's team-perspective EPA is shared **equally** across those flags (`epaCost = teamEPA / k`) rather than each flag receiving the full play EPA.
- **Graceful degradation** (8.5, 8.6): if the source is offline or a play is unmatched, `epaCost = null` and flags are still produced; the Pattern Engine then ranks by **count** instead of cost, and the Alerts_List shows **"cost unavailable"** rather than failing.
- **Label** (8.8): wherever cost is displayed, the UI labels the value **"play EPA (shared)"**, not as the cost of the error itself.

### Pattern Engine (Requirement 9)
- **Grouping dimensions**: player (`nflId`), error type, situation (down, distance band, field zone, score state), opponent alignment and rush type, protection features (rusher count, stunts, play action).
- **Denominator — opportunities** (9.2): `sampleSize` is the number of **opportunities** for that error type in the group, counted per error type:
  - blocker-attributed errors (sack/hit/hurry allowed, beaten, worse-than-expected rep) → the player's **pass-block reps** in that situation;
  - stunt-not-handled → the **stunts faced** by the protection in that group;
  - lost escape lane → the defense's **pass-rush snaps**.
- **Rate and interval** (9.3): `rate = count / opportunities`, with the **Wilson 90% interval** `[rateLow90, rateHigh90]` computed from `count` and `opportunities`.
- **Hiding small samples** (9.5): patterns with `opportunities < pattern_min_opportunities` (default 10, from `config/thresholds.yaml`) are hidden.
- **Ranking** (9.6): descending by `count × avgCost` (frequency × average cost), so high-frequency high-cost patterns rise to the top; when `avgCost` is unavailable because flag costs are null, ranking falls back to **count** (8.6).

### API Design

FastAPI, DuckDB over Parquet, per-play slices only. All list endpoints accept `myTeam`, `opponent`, and `mode` (self|opponent) plus a `games` scope (Requirement 10.1-10.4). `mode = self` scopes to the my-team's own errors; `mode = opponent` scopes to the opponent's errors. The games set is the games between the two selected teams drawn from `games.csv`.

| Method / Path | Query params | Response (shape) |
|---|---|---|
| `GET /plays` | `myTeam, opponent, mode, games, week, down, situation, hasFlag` | `[{gameId, playId, week, offense, defense, down, yardsToGo, result, dropBackType, flagCount}]` |
| `GET /plays/{gameId}/{playId}` | – | `{header{teams, quarter, clock, down, distance, result, coverage, playDescription}, meta{snapFrameId, endOfDropbackFrameId, lineOfScrimmage, firstDownX}, frames:[{frameId, event, objects:[{nflId, team, jersey, x, y, isBall}]}], flags:[Flag], pocketByFrame}` |
| `GET /flags` | `myTeam, opponent, mode, games, confidenceLevel, errorType, player, week, situation` | `[Flag]` |
| `GET /patterns` | `myTeam, opponent, mode, games, perspective(self\|opponent)` | `[{patternId, label, count, rate, rateLow90, rateHigh90, opportunities, sampleSize, avgCost, rankScore, playRefs:[{gameId,playId}]}]` |
| `GET /players/{nflId}` | `myTeam, opponent, mode, games` | `{player{name, position}, metrics:[{name, value, sampleSize}], flags:[Flag], patterns:[...]}` |
| `GET /limitations` | – | `{title, bullets:[...]}` static content (Requirement 15) |

The `/players/{nflId}` metrics include **time to pressure** — time from the snap frame to the first frame the rusher is within `free_rusher_qb_yd` of the QB (Requirement 14.3) — and **win rate by rush type** — the share of engagements in which the rusher passed the blocker or reached `free_rusher_qb_yd` of the QB within 2.5 s, grouped by inside/outside rush lateral direction (Requirement 14.4) — each returned with its `sampleSize`.

`/plays/{...}` returns a single play's frames only — never a whole game — satisfying the memory constraint (Requirement 2.5). Every player metric object includes `sampleSize` (Requirement 14.3).

### Frontend Component Tree

```
<App>  (reads myTeam, opponent, and mode from the URL query params — Requirement 10.1)
 ├─ <TeamSelector>              my-team abbrev + opponent abbrev (both from games.csv) + mode(self|opponent)
 │                              → writes ?myTeam=&opponent=&mode=  ; self shows my-team errors, opponent shows opponent errors (10.1-10.3)
 ├─ <LimitationsLink>           reachable from every screen → <LimitationsNote>
 ├─ <AlertsList>                flags table, filters (confidence, errorType, player, week, situation); cost column labeled "play EPA (shared)", or "cost unavailable" when null (8.6, 8.8)
 │     └─ row click → navigates to <PlayViewer> at errorFrameId   (Requirement 11.3)
 ├─ <PatternsScreen>            tabs: Self-scout | Opponent  (Requirement 12.1)
 │     ├─ <PatternTable>        ranked by rankScore
 │     ├─ <PatternChart>        Recharts bars/intervals (rate + 90% interval)
 │     └─ pattern click → filtered play list                      (Requirement 12.2)
 ├─ <PlayViewer>                (Requirement 13)
 │     ├─ <FieldCanvas>         HTML Canvas renderer
 │     │     • yard lines, LOS, first-down line (13.1)
 │     │     • player dots by team + jersey, ball drawn separately (13.2)
 │     │     • 1s trails w/ full-path toggle (13.4)
 │     │     • pocket outline polygon (13.5)
 │     │     • rings around flagged players (13.7)
 │     │     • animation loop targeting 10fps / 23 objects (13.9)
 │     ├─ <PlayHeader>          teams, qtr, clock, down&dist, result, coverage, desc (13.8)
 │     ├─ <Timeline>            snap/throw/sack markers + flag markers by confidence (13.6)
 │     ├─ <Controls>            play/pause, 0.25x/0.5x/1x, scrubber, arrow-key stepping (13.3)
 │     └─ <PlayerInspect>       click dot → role, alignment, per-play stats (13.7)
 └─ <PlayerPage>                flags, patterns, metrics each with sampleSize (Requirement 14)
```

The `<FieldCanvas>` runs a `requestAnimationFrame` loop that advances the frame index on a fixed 100 ms accumulator (10 fps base, scaled by the speed selector) and redraws all 23 objects per tick; drawing is a single canvas clear + batched fills to hold the frame budget (Requirement 13.9).

## Configuration — `config/thresholds.yaml`

All tunable numbers live here with comments; code reads them rather than embedding literals (Requirement 1.5).

```yaml
field:
  length_yd: 120.0          # full field incl. end zones, for x-normalization
  width_yd: 53.3            # for y-normalization
  frame_rate_hz: 10         # tracking sample rate; time_since_snap = frames / 10

engagement:
  distance_yd: 1.5          # blocker-rusher proximity to count as engaged
  min_consecutive_frames: 3 # engagement must persist >= 3 frames

rusher:
  getoff_speed_yps: 2.0     # speed threshold defining get-off moment
  set_point_fallback_seconds: 0.5 # when no velocity stop within 1.0s of snap, use position at this time

level2:
  free_rusher_qb_yd: 3.0    # rusher-to-QB distance that triggers free-rusher rule
  stunt_window_s: 2.0       # window within which crossing paths count as a stunt
  # Blocker-count rules count only pass blockers whose block type is NOT CH, SR, or NB
  excluded_block_types: [CH, SR, NB]

level3:
  rep_threshold: 50         # below this rep count, shrink toward position average
  rep_residual_sigma: 2.0   # how far worse than expected before a Possible flag
  pressure_spike_delta: 0.25 # probability rise over the window that triggers attribution
  pressure_spike_window: 5  # frames; spike = rise >= delta within this sliding window

patterns:
  interval_confidence: 0.90 # Wilson interval confidence level
  distance_bands: [3, 7]    # short / medium / long distance-to-go cut points
  min_opportunities: 10     # hide patterns with fewer opportunities than this

cost:
  nflverse_offline_ok: true # produce flags with null epaCost when EPA unavailable
```

## Error Handling

- **Offline EPA** (8.5, 8.6): catch download/network failure, log once, continue with `epaCost = null`; the Pattern Engine ranks by count and the UI shows "cost unavailable" rather than failing.
- **Unresolved snap/end-of-dropback** (2.2, 2.3): play marked `resolved=false`, excluded from features/detection, logged to `reports/data_check.md`; no flags emitted for it, preserving the resolvable-error-frame invariant.
- **Missing QB position**: pocket area, closest-approach, and QB-relative rules for that frame are skipped and the play is flagged `resolved=false` if the QB is absent at the snap; partial gaps interpolate within the dropback window.
- **Missing PFF fields** (`pff_nflIdBlockedPlayer`, `pff_positionLinedUp`): engagement cross-check records `pffBlockedConsistent=null` and detection falls back to tracking-derived role; Level 1 rules simply do not fire for rows whose required PFF label is NA. Missing-value rates are reported in `reports/data_check.md` (2.4).

## Testing Strategy

**Backend (pytest):**
- Geometry primitives against hand-made fixtures with known answers (distance, shoelace area, convex hull, crossing, flip), including a convex-hull-area test on unordered points of known area — Requirement 4.7.
- Property-based tests for the invariants listed below (normalization involution, pocket area = shoelace of convex hull independent of ordering, engagement run length, flag schema + resolvable frame, Level 1 error-frame derivation, sample-size presence, train/test disjointness, no cross-game leakage, shrinkage convexity, cost conservation, Wilson bounds, ranking order).
- Level 1 fixtures (plays with/without PFF labels and penalties) asserting correct attribution.
- Level 2 crafted plays triggering each rule and asserting error-frame placement; by-game split assertions for Level 3; calibration run on a small fixture set asserting report generation.
- Cost merge tests with fixture nflverse rows (matched → value, unmatched/offline → null).

**Frontend (component tests):** a small set — `TeamSelector` writes the URL mode and rescopes; `AlertsList` row click routes to the viewer at the error frame; `Timeline` renders flag markers colored by confidence.

**Make-command verification:** `make test` runs pytest + frontend tests; a smoke check confirms `make data` then `make dev` complete on a fresh clone with only documented prerequisites (Requirement 1.4, 16.2).

Property tests run ≥ 100 iterations each and are tagged `Feature: pass-protection-error-finder, Property {n}: {text}`.

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Direction normalization is involutive on left plays

*For any* tracking row with coordinates `x ∈ [0,120]`, `y ∈ [0,53.3]`, and angles `o, dir ∈ [0,360)`, applying the left-play normalization twice returns the original values (within floating-point tolerance), and applying it to a right-play row leaves it unchanged.

**Validates: Requirements 3.1**

### Property 2: Time since snap is monotonic and zero at the snap

*For any* resolved play and any two frames after the snap, `timeSinceSnap` increases by exactly 0.1 s per frame and equals 0.0 at the snap frame.

**Validates: Requirements 3.3**

### Property 3: Pocket area equals the shoelace area of the convex hull, independent of input ordering

*For any* unordered set of player positions (pass blockers plus the QB), the computed pocket area equals the shoelace area of the convex hull of those points, is greater than or equal to zero, and is unchanged when the input points are supplied in any order.

**Validates: Requirements 4.1, 4.7**

### Property 4: Distance is symmetric and non-negative

*For any* two points p and q, `distance(p, q) == distance(q, p)` and the result is greater than or equal to zero.

**Validates: Requirements 4.7**

### Property 5: Direction flip is involutive

*For any* angle d in [0,360), flipping twice returns d (modulo 360).

**Validates: Requirements 4.7**

### Property 6: Every engagement spans at least three consecutive in-range frames

*For any* blocker-rusher distance series, every emitted engagement covers at least 3 consecutive frames all within the engagement distance threshold, and no engagement is emitted for any shorter in-range run.

**Validates: Requirements 4.3**

### Property 7: Every flag carries required fields and a resolvable error frame

*For any* emitted Flag, the gameId, playId, errorFrameId, involvedNflIds, team, errorType, confidenceLevel, and explanation are all present, and `snapFrameId ≤ errorFrameId ≤ lastFrameId` for that play.

**Validates: Requirements 8.1, 11.3, 13.6**

### Property 8: Every Level 1 flag's error frame matches its documented derivation

*For any* emitted Level 1 (Confirmed) Flag, the `errorFrameId` equals the frame produced by the documented derivation for its type — the snap frame for a penalty, the engaged (or `pff_nflIdBlockedPlayer`) rusher's closest-approach-to-QB frame for a sack/hit/hurry allowed, and the frame the rusher passes the blocker (falling back to that rusher's closest-approach frame) for a beaten-by-defender flag — and in all cases lies within `[snapFrameId, lastFrameId]`.

**Validates: Requirements 5.1, 5.2, 5.3, 5.4**

### Property 9: No player-level statistic is presented without its sample size

*For any* player-level statistic emitted by the pipeline, API, or player page, a sampleSize field is present and is an integer greater than or equal to zero.

**Validates: Requirements 7.9, 14.5**

### Property 10: Train and test game sets are disjoint

*For any* input list of games and any split, the set of gameIds in the training set and the set of gameIds in the test set share no element, and every row of a play stays entirely on one side.

**Validates: Requirements 7.6**

### Property 11: Level 3 features use no data from a play's own held-out game

*For any* play in the held-out (test) set, every game that contributes to that play's Level 3 player-history feature vector is a training game — none is the play's own game — so no feature for a play uses data derived from that play's own held-out game.

**Validates: Requirements 7.7**

### Property 12: Low-rep shrinkage is a convex combination toward the position average

*For any* raw player estimate, position average, and rep count, the shrunk estimate lies between the raw estimate and the position average, approaches the position average as reps approach zero, and approaches the raw estimate as reps grow large.

**Validates: Requirements 7.8**

### Property 13: Shared costs sum to the play's team-perspective EPA

*For any* play that has k ≥ 1 flags and a defined play EPA, the sum of the k shared `epaCost` values equals the play's team-perspective EPA (with the EPA sign flipped for defensive errors) within floating-point tolerance.

**Validates: Requirements 8.2, 8.3**

### Property 14: Pattern rate interval is well-formed

*For any* pattern with count k and opportunities n (with n greater than zero and k not exceeding n), `rate == k / n` and the Wilson 90% interval computed from k and n satisfies `0 ≤ rateLow90 ≤ rate ≤ rateHigh90 ≤ 1`.

**Validates: Requirements 9.3**

### Property 15: Patterns are ranked by frequency times average cost

*For any* set of patterns, the emitted ordering is non-increasing in `count × avgCost`.

**Validates: Requirements 9.6**
