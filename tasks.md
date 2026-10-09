# Implementation Plan: Pass Protection Error Finder

## Overview

This plan turns the design into incremental, test-backed coding steps grouped into six phases (0–5). Each phase ends with an explicit **Review Gate** — a stop-and-review checkpoint where the user inspects the tables, reports, and running UI produced so far before the next phase begins. Earlier phases produce the data foundation and a working play viewer with no flags; later phases layer the three detection levels, the cost engine, and the pattern/player screens on top. Tasks marked `*` are optional (tests and enhancements can be skipped for a faster path); every non-`*` sub-task is core and must be implemented. Each task cites the requirement IDs it implements and, where relevant, the design Correctness Property it validates.

Language and stack are fixed by the design: Python 3.11+ (Polars, DuckDB, FastAPI, scikit-learn, LightGBM) for the backend and React + TypeScript + Vite with HTML Canvas for the frontend. No language selection is needed.

---

## Tasks

### Phase 0 — Data Check and Foundation

Goal: a reproducible monorepo, raw data relocated, a one-time Parquet conversion, Section 2 data-quality findings written to `reports/data_check.md`, and a single robust snap / end-of-dropback resolver with tests. No detection, no UI yet.

- [ ] 1. Scaffold the monorepo and reproducible setup
  - [ ] 1.1 Create the monorepo skeleton and tooling config
    - Create `backend/` (Python 3.11+ package with `pipeline/`, `api/`, `tests/`), `frontend/` (React + TS + Vite app with `src/` and `src/__tests__/`), and top-level `data/raw/`, `data/processed/`, `models/`, `reports/`, `config/` directories
    - Add `backend/pyproject.toml` pinning Polars, DuckDB, FastAPI, uvicorn, scikit-learn, LightGBM, pytest, hypothesis; add `frontend/package.json` with React, TypeScript, Vite, Recharts, and a component-test runner (Vitest + Testing Library)
    - _Requirements: 1.1, 1.6_

  - [ ] 1.2 Create the root Makefile with `data`, `dev`, and `test` targets
    - `make data` runs the full pipeline module; `make dev` starts the FastAPI server and the Vite dev server; `make test` runs pytest plus frontend component tests
    - Document prerequisites so a fresh clone runs `make data` then `make dev` without further manual steps
    - _Requirements: 1.3, 1.4, 16.2_

  - [ ] 1.3 Create `config/thresholds.yaml` and a typed config loader
    - Write the full thresholds file from the design (field, engagement, rusher, level2, level3, patterns, cost sections) with explanatory comments
    - Ensure the file includes `patterns.min_opportunities` (default 10), `level3.pressure_spike_window` (default 5 frames), `rusher.set_point_fallback_seconds` (default 0.5 s), and `level2.excluded_block_types` (`[CH, SR, NB]`) alongside the existing `pressure_spike_delta` and `free_rusher_qb_yd` thresholds
    - Implement `backend/pipeline/config.py` that loads the YAML once and exposes typed accessors; no numeric literals elsewhere in code
    - _Requirements: 1.5_

  - [ ] 1.4 Relocate raw CSVs into `data/raw/`
    - Move `games.csv`, `plays.csv`, `players.csv`, `pffScoutingData.csv`, and the `tracking/*.csv` files from the existing data folder into `data/raw/`; update any path references
    - _Requirements: 1.2_

- [ ] 2. Build the snap / end-of-dropback resolver
  - [ ] 2.1 Implement `resolve_play_frames` with fallback precedence
    - In `backend/pipeline/resolve.py`, implement `resolve_play_frames(play_tracking) -> (snapFrameId, endOfDropbackFrameId, resolved, reason)` using snap precedence `ball_snap → autoevent_ballsnap` and end-of-dropback precedence `pass_forward → autoevent_passforward → qb_sack/strip_sack → run(scramble) → last recognized terminal event`
    - Mark a play `resolved = false` with an `unresolvedReason` when no snap variant, no end variant, or end precedes snap; such plays are excluded downstream and never emit flags
    - _Requirements: 2.2, 2.3_

  - [ ] 2.2 Write unit tests for the resolver
    - Hand-made plays exercising each precedence branch, manual-over-automatic preference, and all three unresolved cases (no snap, no end, end-before-snap)
    - _Requirements: 2.2, 2.3_

- [ ] 3. Run the data check and convert tracking to Parquet
  - [ ] 3.1 Compute data-check statistics
    - In `backend/pipeline/data_check.py`, compute distinct event values and the last event per play, survey snap and end-of-dropback event variants via the resolver, and compute missing-value rates for `pff_nflIdBlockedPlayer`, `pff_positionLinedUp`, and the tracking coordinate/motion fields
    - _Requirements: 2.1, 2.4_

  - [ ] 3.2 Convert tracking CSVs to Parquet once
    - In `backend/pipeline/ingest.py`, read the 122 tracking CSVs with Polars and write Parquet to `data/processed/` (partitioned by `gameId` where it helps pruning); the conversion runs once and later stages query Parquet via DuckDB/Polars rather than re-reading CSVs
    - _Requirements: 2.5, 1.2_

  - [ ] 3.3 Write `reports/data_check.md`
    - Emit the findings from 3.1 plus the list of unresolved plays with their `(gameId, playId)` and reason
    - _Requirements: 2.6_

- [ ] 4. Review Gate — Phase 0
  - Confirm `make data` converts tracking to Parquet on a fresh clone, `reports/data_check.md` is populated, and resolver tests pass. **Ensure all tests pass, ask the user if questions arise.**
  - _Requirements: 16.1, 16.2_

---

### Phase 1 — Play Viewer (no flags)

Goal: preprocessing (normalization, LOS, time-since-snap, PFF join), a tested geometry module, a FastAPI frames endpoint, and a React Canvas animated field with timeline, event markers, and controls. The user can pick any play and watch it. No flags are produced yet.

- [ ] 5. Preprocessing and normalization
  - [ ] 5.1 Implement direction normalization and enrichment
    - In `backend/pipeline/normalize.py`, apply the left-play transform (`x=120-x`, `y=53.3-y`, `o=(o+180)%360`, `dir=(dir+180)%360`), compute Line_Of_Scrimmage as normalized ball x at the snap frame, compute `timeSinceSnap = (frameId - snapFrameId)/10`, and tag ball rows (`nflId` NA → `isBall=true`, `team=football`)
    - _Requirements: 3.1, 3.2, 3.3, 3.5_

  - [ ] 5.2 Join PFF role and alignment onto tracking and write `tracking_norm`
    - Join `pff_role` and `pff_positionLinedUp` by `(gameId, playId, nflId)` onto every tracking row; write the `tracking_norm` Parquet table
    - _Requirements: 3.4_

  - [ ]* 5.3 Property tests for normalization and time-since-snap
    - **Property 1: Direction normalization is involutive on left plays** — **Validates: Requirements 3.1**
    - **Property 2: Time since snap is monotonic and zero at the snap** — **Validates: Requirements 3.3**
    - _Requirements: 3.1, 3.3_

- [ ] 6. Geometry module
  - [ ] 6.1 Implement pure geometry primitives
    - In `backend/pipeline/geometry.py`, implement Euclidean distance, shoelace polygon area (absolute value), a `convex_hull` primitive (monotone-chain hull of an unordered point set returning vertices in counter-clockwise order), segment crossing (orientation-sign test), and direction flip `(d+180)%360`
    - Compose `convex_hull` with the shoelace primitive so pocket area is computed as the shoelace area of the convex hull of the pass-blocker positions together with the QB
    - _Requirements: 4.1, 4.7_

  - [ ] 6.2 Unit + property tests for geometry primitives
    - Hand-made fixtures with known answers for distance, area, crossing, and flip
    - Add a convex-hull-area test that supplies **unordered** input points whose correct area is known and asserts the computed pocket area equals that known value regardless of input ordering
    - **Property 3: Pocket area equals the shoelace area of the convex hull, independent of input ordering** — **Validates: Requirements 4.1, 4.7**
    - **Property 4: Distance is symmetric and non-negative** — **Validates: Requirements 4.7**
    - **Property 5: Direction flip is involutive** — **Validates: Requirements 4.7**
    - _Requirements: 4.1, 4.7_

- [ ] 7. FastAPI service and frames endpoint
  - [ ] 7.1 Create the FastAPI app and DuckDB-over-Parquet access layer
    - In `backend/api/`, create the app, a DuckDB connection helper that queries `data/processed/` Parquet, and JSON serializers; never load a whole game into memory
    - _Requirements: 2.5, 1.6_

  - [ ] 7.2 Implement `GET /plays` and `GET /plays/{gameId}/{playId}`
    - `/plays` returns the scoped play list and accepts `myTeam`, `opponent`, and `mode` (self|opponent) plus a `games` scope so the list is restricted to the games between the two selected teams; `/plays/{...}` returns one play's header, meta (snap/end/LOS/first-down), per-frame objects, and `pocketByFrame` — a single play's frames only
    - _Requirements: 2.5, 13.8, 10.1, 10.4_

  - [ ]* 7.3 API tests for the plays/frames endpoints
    - Assert `/plays/{...}` returns only one play's frames and includes meta and header fields
    - _Requirements: 2.5, 13.8_

- [ ] 8. React Canvas play viewer
  - [ ] 8.1 Build the API client and app shell with routing
    - In `frontend/src/`, create a typed API client and the `<App>` shell with routes for the viewer; add a play picker that loads any play
    - _Requirements: 13.8_

  - [ ] 8.2 Implement `<FieldCanvas>` animated renderer
    - Draw yard lines, LOS, and first-down line; player dots colored by team with jersey numbers; the ball drawn separately; 1-second trails with a full-path toggle; a `requestAnimationFrame` loop on a 100 ms accumulator targeting 10 fps for 23 objects via a single clear + batched fills
    - _Requirements: 13.1, 13.2, 13.4, 13.9_

  - [ ] 8.3 Implement `<PlayHeader>`, `<Timeline>` (events only), and `<Controls>`
    - Header with teams, quarter, clock, down & distance, result, coverage, and description; timeline with snap/throw/sack event markers (no flag markers yet); controls for play/pause, 0.25x/0.5x/1x, scrubber, and arrow-key stepping
    - _Requirements: 13.3, 13.6, 13.8_

  - [ ]* 8.4 Component test for the viewer controls
    - Assert speed selection and scrubber update the rendered frame index
    - _Requirements: 13.3_

- [ ] 9. Review Gate — Phase 1
  - Confirm any play can be selected and watched smoothly with header, event timeline, and controls, and geometry/preprocessing tests pass. **Ensure all tests pass, ask the user if questions arise.**
  - _Requirements: 16.1, 16.2_

---

### Phase 2 — Level 1 Flags and Alerts List

Goal: confirmed-error detection, the stable flag schema persisted to Parquet, a flags API, timeline flag markers, the alerts list screen, and the my-team / opponent URL switch.

- [ ] 10. Flag schema and Level 1 detection
  - [ ] 10.1 Define the canonical Flag schema and writer
    - In `backend/pipeline/detect/flag.py`, define the stable flag record (`flagId, gameId, playId, errorFrameId, involvedNflIds, team, errorType, confidenceLevel, explanation, epaCost, detail`) with the resolvable-frame invariant `snapFrameId ≤ errorFrameId ≤ lastFrameId`, a deterministic `flagId` hash, and a `flags` Parquet writer; design the schema to be broadcaster-reusable
    - Record the per-type `errorFrameId` derivation in the schema contract: penalty → snap frame; sack/hit/hurry allowed → the engaged (or `pff_nflIdBlockedPlayer`) rusher's closest-approach-to-QB frame; beatenByDefender → the frame the rusher passes the blocker, falling back to that rusher's closest-approach frame
    - _Requirements: 8.1, 16.4, 5.1, 5.2, 5.3, 5.4, 5.5_

  - [ ] 10.2 Implement Level 1 Confirmed detection
    - In `backend/pipeline/detect/level1.py`, emit flags for `foulName*`+`foulNFLId*` penalties (errorFrameId = snap frame), for `pff_sackAllowed|pff_hitAllowed|pff_hurryAllowed==1` (errorFrameId = the closest-approach-to-QB frame of the engaged rusher, or the rusher named by `pff_nflIdBlockedPlayer`), and for `pff_beatenByDefender==1` (errorFrameId = the frame the rusher passes the blocker, falling back to that rusher's closest-approach frame when the pass-moment cannot be determined), using recorded data only with no modeling; skip rows whose required PFF label is NA
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [ ] 10.3 Tests for Level 1 attribution and flag invariants
    - Fixtures with/without PFF labels and penalties asserting correct player attribution, correct per-type error-frame derivation, and no-fire on NA labels
    - **Property 7: Every flag carries required fields and a resolvable error frame** — **Validates: Requirements 8.1, 11.3, 13.6**
    - **Property 8: Every Level 1 flag's error frame matches its documented derivation** — **Validates: Requirements 5.1, 5.2, 5.3, 5.4**
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 8.1_

- [ ] 11. Flags API and team scoping
  - [ ] 11.1 Implement `GET /flags` with scoping and attach flags to the play endpoint
    - `/flags` accepts `myTeam, opponent, mode, games, confidenceLevel, errorType, player, week, situation`; `mode=self` scopes to the my-team's own errors and `mode=opponent` scopes to the opponent's errors; `/plays/{...}` now returns the play's flags array
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 11.1, 11.2_

  - [ ]* 11.2 API test for flag scoping
    - Assert myTeam/opponent/mode and game scoping filters the returned flags (self vs opponent perspective)
    - _Requirements: 10.2, 10.3, 10.4_

- [ ] 12. Alerts list, team selector, and timeline flag markers
  - [ ] 12.1 Implement `<TeamSelector>` writing teams and mode to the URL
    - My-team abbreviation + opponent abbreviation controls, both drawn from `games.csv`, at the top of the app; store `myTeam`, `opponent`, and `mode` (self|opponent) in the URL query params and rescope screens on change; self mode shows the my-team's own errors, opponent mode shows the opponent's errors
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [ ] 12.2 Implement `<AlertsList>` with filters and row-click navigation
    - Table of all flags for the selected team and games; filters for confidence, error type, player, week, and situation; cost column labeled "play EPA (shared)", showing "cost unavailable" when `epaCost` is null; row click opens `<PlayViewer>` at the flag's `errorFrameId`
    - _Requirements: 11.1, 11.2, 11.3, 8.6, 8.8_

  - [ ] 12.3 Add flag markers to `<Timeline>` and rings around flagged players
    - Flag markers colored by confidence level on the timeline; draw a ring around flagged players and show role/alignment/per-play stats on dot click
    - _Requirements: 13.6, 13.7_

  - [ ]* 12.4 Component tests for selector, alerts, and timeline
    - `TeamSelector` writes myTeam/opponent/mode to the URL and rescopes; `AlertsList` row click routes to the viewer at the error frame; `Timeline` renders flag markers colored by confidence
    - _Requirements: 10.1, 11.3, 13.6_

- [ ] 13. Review Gate — Phase 2
  - Confirm Level 1 flags persist, appear in the alerts list and on the timeline, open the viewer at the error frame, and the team switch rescopes the UI. **Ensure all tests pass, ask the user if questions arise.**
  - _Requirements: 16.1, 16.2_

---

### Phase 3 — Features and Level 2 Rules

Goal: the full feature/measurement set (engagements, depth conceded, pocket, rush path, closest approach, get-off), the four Level 2 rules, calibration against Level 1 written to `reports/level2_calibration.md`, and Level 2 flags shown in the UI labeled "Likely: check the film".

- [ ] 14. Feature and measurement computation
  - [ ] 14.1 Compute engagements and the blocker set point, write the `engagements` table
    - For each blocker↔rusher pair, detect runs of ≥3 consecutive frames within `engagement.distance_yd`, record start/end/min-distance, and cross-check against `pff_nflIdBlockedPlayer` into `pffBlockedConsistent`
    - Compute the blocker set point as the velocity-stop frame within 1.0 s of the snap at which the blocker's forward velocity first stops; when no clear stop occurs within 1.0 s, fall back to the blocker's position at `rusher.set_point_fallback_seconds` (default 0.5 s) after the snap and record `setPointFallbackUsed = true`
    - _Requirements: 4.3, 4.8, 4.9_

  - [ ]* 14.2 Property test for engagement run length
    - **Property 6: Every engagement spans at least three consecutive in-range frames** — **Validates: Requirements 4.3**
    - _Requirements: 4.3_

  - [ ] 14.3 Compute play-level and player-level measurements
    - In `backend/pipeline/features.py`, compute `play_features` (time to throw, rusher/blocker counts, pressure, pocket area per frame as the shoelace area of the convex hull of pass blockers + QB, pocket shrink rate) and `player_measurements` (get-off time, depth conceded at 1.0/1.5/2.0/2.5 s, closest approach distance+frame, rush lateral direction, speed at first contact, crossed-with-rusher)
    - Compute `timeToPressure` as the time from the snap frame to the first frame the rusher is within `free_rusher_qb_yd` of the QB, and the win-rate-by-rush-type inputs `rusherPassedBlocker` and `reachedQbWithin2_5s` (whether the rusher passed the blocker or reached `free_rusher_qb_yd` of the QB within 2.5 s), grouped by inside/outside; persist both tables
    - _Requirements: 4.1, 4.2, 4.4, 4.5, 4.6, 14.3, 14.4_

  - [ ]* 14.4 Unit tests for composed measurements
    - Hand-made plays asserting get-off time, depth conceded relative to set point, pocket area/shrink, closest approach, time to pressure, and win-rate-by-rush-type inputs
    - _Requirements: 4.1, 4.2, 4.4, 4.6, 14.3, 14.4_

- [ ] 15. Level 2 rule detection
  - [ ] 15.1 Implement the four Level 2 rules as explicit code
    - In `backend/pipeline/detect/level2.py`: free rusher (6.1, error frame = line-of-blockers crossing), wasted double team (6.2), stunt not handled (6.3), lost escape lane (6.4); each reads thresholds from config and labels flags "Likely: check the film"
    - Wherever a rule uses a blocker count, count only pass blockers whose block type is **not** `CH`, `SR`, or `NB` (from `level2.excluded_block_types`)
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [ ] 15.2 Tests for each Level 2 rule and error-frame placement
    - Crafted plays triggering each rule and asserting correct error-frame placement, including a case verifying `CH`/`SR`/`NB` blockers are excluded from the blocker count
    - **Property 7: Every flag carries required fields and a resolvable error frame** — **Validates: Requirements 8.1, 11.3, 13.6**
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.6_

  - [ ] 15.3 Calibrate Level 2 on training games and write `reports/level2_calibration.md`
    - Tune Level 2 thresholds on training games only; compute and report each rule's precision/recall vs the Level 1 PFF labels on held-out games only; for the lost escape lane rule record "no answer key" (no PFF label can confirm it) and validate that rule by manual review of a sample of flagged plays instead of against PFF labels
    - _Requirements: 6.7, 6.8_

  - [ ]* 15.4 Test calibration report generation
    - Run calibration on a small fixture set and assert the report is produced with per-rule precision/recall and the "no answer key" entry for the lost escape lane rule
    - _Requirements: 6.7, 6.8_

- [ ] 16. Surface Level 2 flags in the UI
  - [ ] 16.1 Render Level 2 flags with the "Likely" label
    - Level 2 flags flow through the existing flags API, alerts list, and timeline markers; display the "Likely: check the film" label and the "play EPA (shared)" / "cost unavailable" cost labels
    - _Requirements: 6.5, 11.1, 13.6, 8.8_

- [ ] 17. Review Gate — Phase 3
  - Confirm feature tables, Level 2 flags, and the calibration report are produced, and Level 2 flags appear in the UI labeled "Likely". **Ensure all tests pass, ask the user if questions arise.**
  - _Requirements: 16.1, 16.2_

---

### Phase 4 — Level 3 Models and Cost Engine

Goal: a baseline expected-rep model then a LightGBM upgrade, a per-frame pressure-probability model, by-game splits, held-out metrics in `reports/models.md`, the nflverse EPA cost engine joined to flags, and Level 3 flags labeled "Possible: film to review".

- [ ] 18. By-game split and low-rep shrinkage utilities
  - [ ] 18.1 Implement by-game train/test split, leakage-free history, and shrinkage
    - In `backend/pipeline/detect/split.py`, split train/test strictly by `gameId` (no random frame/play split, whole plays stay on one side); compute Level 3 player-history features from training games only or by leave-one-game-out, so no feature for a play uses data derived from that play's own held-out game; implement empirical-Bayes shrinkage of low-rep player history toward position averages below `rep_threshold`; track rep counts everywhere
    - _Requirements: 7.6, 7.7, 7.8_

  - [ ] 18.2 Property tests for split disjointness, no leakage, and shrinkage
    - **Property 10: Train and test game sets are disjoint** — **Validates: Requirements 7.6**
    - **Property 11: Level 3 features use no data from a play's own held-out game** — **Validates: Requirements 7.7**
    - **Property 12: Low-rep shrinkage is a convex combination toward the position average** — **Validates: Requirements 7.8**
    - _Requirements: 7.6, 7.7, 7.8_

- [ ] 19. Expected-rep model (baseline then GBM)
  - [ ] 19.1 Establish the situational-average baseline
    - In `backend/pipeline/detect/expected_rep.py`, compute situational averages for depth conceded at 1.5 s and probability of being beaten by 2.5 s per engagement before any GBM, using leakage-free player history (training games only / leave-one-game-out)
    - _Requirements: 7.1, 7.2, 7.7_

  - [ ] 19.2 Train the LightGBM expected-rep model and emit worse-than-expected flags
    - Train on alignments, player history (shrunk, leakage-free), rusher/blocker counts, down & distance; emit a Possible flag when a rep's residual exceeds `rep_residual_sigma`; persist the model under `models/`
    - _Requirements: 7.1, 7.2, 7.5, 7.7_

- [ ] 20. Pressure-probability model
  - [ ] 20.1 Train the per-frame pressure model and emit pressure-spike flags
    - In `backend/pipeline/detect/pressure.py`, estimate per-frame pressure probability from positions/speeds of rushers, blockers, and QB, trained on PFF hit/hurry/sack labels using leakage-free player history; detect a pressure spike as a rise of at least `pressure_spike_delta` (0.25) within a sliding `pressure_spike_window` of 5 frames (not a single-frame jump), emit a flag attributed to the blocker nearest the causing rusher; persist the model
    - _Requirements: 7.3, 7.4, 7.5, 7.7_

  - [ ] 20.2 Report held-out metrics to `reports/models.md`
    - Write AUC + calibration plot for the pressure model and depth error for the expected-rep model on held-out games
    - _Requirements: 7.10_

  - [ ]* 20.3 Tests for Level 3 flag labeling and sample-size presence
    - Assert Possible flags are labeled "Possible: film to review" and model-backed player stats carry sample sizes
    - **Property 9: No player-level statistic is presented without its sample size** — **Validates: Requirements 7.9, 14.5**
    - _Requirements: 7.5, 7.9_

- [ ] 21. Cost engine
  - [ ] 21.1 Implement the nflverse EPA cost engine with team perspective, equal split, caching, and graceful degradation
    - In `backend/pipeline/cost.py`, auto-download nflverse play-by-play EPA to `data/processed/epa_cache.parquet`, merge `(gameId, playId)` → `(old_game_id, play_id)`, express cost from the charged team's perspective (flip the EPA sign for defensive errors), and share the play's team-perspective EPA equally across all flags on the play (`epaCost = teamEPA / k`); set `epaCost = null` when offline or unmatched while still producing flags, so the Pattern Engine ranks by count and the UI shows "cost unavailable"
    - Label the stored/displayed value "play EPA (shared)", not the cost of the error itself
    - _Requirements: 8.2, 8.3, 8.4, 8.5, 8.6, 8.8_

  - [ ]* 21.2 Cost merge and conservation tests
    - Fixture nflverse rows: matched → value, unmatched/offline → null; defensive error flips the EPA sign; multiple flags on one play split the team EPA equally
    - **Property 13: Shared costs sum to the play's team-perspective EPA** — **Validates: Requirements 8.2, 8.3**
    - _Requirements: 8.2, 8.3, 8.4, 8.5_

- [ ] 22. Surface Level 3 flags in the UI
  - [ ] 22.1 Render Level 3 flags with the "Possible" label and cost
    - Level 3 flags flow through the flags API and UI with the "Possible: film to review" label; show `epaCost` labeled "play EPA (shared)" or "cost unavailable" when null
    - _Requirements: 7.5, 8.6, 8.8_

- [ ] 23. Review Gate — Phase 4
  - Confirm the baseline-then-GBM expected-rep model, the pressure model, by-game splits, `reports/models.md`, and EPA-costed Level 3 flags are produced and shown. **Ensure all tests pass, ask the user if questions arise.**
  - _Requirements: 16.1, 16.2_

---

### Phase 5 — Patterns and Player Pages

Goal: the pattern engine (grouping, opportunities denominators, Wilson 90% intervals, ranking), the patterns screen with self-scout / opponent tabs, the player page with sample sizes, and the "What this tool can't tell you" note reachable from every screen.

- [ ] 24. Pattern engine
  - [ ] 24.1 Implement grouping, opportunities denominators, Wilson intervals, and ranking
    - In `backend/pipeline/patterns.py`, group flags by player, error type, situation (down, distance band, field zone, score state), opponent alignment/rush type, and protection features (rusher count, stunts, play action)
    - Compute the `opportunities` denominator per error type — pass-block reps in that situation for blocker-attributed errors, stunts faced for stunt-not-handled, the defense's pass-rush snaps for lost escape lane; set `sampleSize = opportunities`, `rate = count / opportunities`, and the Wilson 90% interval from `count` and `opportunities`; hide patterns with `opportunities < patterns.min_opportunities` (default 10); rank by `count × avgCost`; write the `patterns` table
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

  - [ ]* 24.2 Property tests for rate/interval bounds and ranking order
    - **Property 14: Pattern rate interval is well-formed** (`rate == count / opportunities` and Wilson 90% interval bounds) — **Validates: Requirements 9.3**
    - **Property 15: Patterns are ranked by frequency times average cost** — **Validates: Requirements 9.6**
    - _Requirements: 9.3, 9.6_

- [ ] 25. Patterns and player APIs
  - [ ] 25.1 Implement `GET /patterns`, `GET /players/{nflId}`, and `GET /limitations`
    - `/patterns` and `/players/{nflId}` accept `myTeam`, `opponent`, `mode`, and `games` scoping (plus `perspective` for patterns); `/patterns` returns ranked patterns with play refs; `/players/{nflId}` returns player metrics each with `sampleSize`, flags, and patterns; `/limitations` returns the static note content
    - _Requirements: 9.2, 9.3, 10.1, 10.4, 12.1, 14.1, 14.2, 14.3, 14.4, 15.1, 15.2_

  - [ ]* 25.2 API test for sample-size presence on player metrics
    - **Property 9: No player-level statistic is presented without its sample size** — **Validates: Requirements 7.9, 14.5**
    - _Requirements: 14.5_

- [ ] 26. Patterns screen, player page, and limitations note
  - [ ] 26.1 Implement `<PatternsScreen>` with Self-scout and Opponent tabs
    - Ranked pattern table (by rank score) and a Recharts chart of rate + 90% interval; selecting a pattern links to its plays
    - _Requirements: 12.1, 12.2_

  - [ ] 26.2 Implement `<PlayerPage>` with metrics and sample sizes
    - Show the player's flags and patterns; key metrics (get-off time, time to pressure, depth conceded, win rate by rush type); display time to pressure as snap-to-first-frame-within-`free_rusher_qb_yd`-of-QB and win rate by rush type as the share of engagements where the rusher passed the blocker or reached pressure distance within 2.5 s, grouped inside/outside; every metric displayed with its sample size
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5_

  - [ ] 26.3 Implement the limitations note reachable from every screen
    - `<LimitationsLink>` on every screen opening `<LimitationsNote>` stating play call unknown, pass plays only / no run blocking, tracking ends around the throw, and small eight-week samples
    - _Requirements: 15.1, 15.2_

  - [ ]* 26.4 Component test for patterns tabs and limitations reachability
    - Assert the Self-scout/Opponent tabs switch perspective and the limitations link is present on each screen
    - _Requirements: 12.1, 15.1_

- [ ] 27. Final Review Gate — Phase 5
  - Confirm patterns rank correctly with intervals, the player page shows sample-sized metrics, and the limitations note is reachable everywhere; run `make test` and the fresh-clone `make data` → `make dev` smoke check. **Ensure all tests pass, ask the user if questions arise.**
  - _Requirements: 16.1, 16.2_

## Notes

- Tasks marked with `*` are optional (tests and enhancements) and can be skipped for a faster MVP; all other sub-tasks are core and must be implemented. Note that the resolver tests (2.2), geometry tests (6.2), Level 1 attribution/invariant tests (10.3), Level 2 rule tests (15.2), and by-game split/leakage/shrinkage tests (18.2) are **required** (no `*`), because they guard the foundational invariants the rest of the pipeline relies on.
- Each phase ends with a Review Gate — a deliberate stop-and-review before the next phase, satisfying Requirement 16.1. Phase boundaries match the brief: 0 data check/foundation, 1 play viewer (no flags), 2 Level 1 + alerts, 3 features + Level 2, 4 Level 3 models + cost, 5 patterns + player pages.
- Out-of-scope items (live feeds, broadcaster mode, coverage errors by DBs, tackling/pursuit, user accounts, video) are intentionally absent per Requirement 16.3; the Flag schema stays broadcaster-reusable per Requirement 16.4.
- Property tests reference the design's Correctness Properties and run ≥100 iterations each, tagged `Feature: pass-protection-error-finder, Property {n}`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "1.4", "2.1"] },
    { "id": 2, "tasks": ["2.2", "3.1", "3.2"] },
    { "id": 3, "tasks": ["3.3", "5.1", "6.1"] },
    { "id": 4, "tasks": ["5.2", "5.3", "6.2", "7.1"] },
    { "id": 5, "tasks": ["7.2", "7.3", "8.1"] },
    { "id": 6, "tasks": ["8.2", "8.3", "8.4", "10.1"] },
    { "id": 7, "tasks": ["10.2", "10.3", "14.1", "14.3"] },
    { "id": 8, "tasks": ["11.1", "14.2", "14.4", "15.1"] },
    { "id": 9, "tasks": ["11.2", "12.1", "15.2", "15.3"] },
    { "id": 10, "tasks": ["12.2", "12.3", "15.4", "16.1", "18.1"] },
    { "id": 11, "tasks": ["12.4", "18.2", "19.1", "21.1"] },
    { "id": 12, "tasks": ["19.2", "20.1", "21.2"] },
    { "id": 13, "tasks": ["20.2", "20.3", "22.1", "24.1"] },
    { "id": 14, "tasks": ["24.2", "25.1"] },
    { "id": 15, "tasks": ["25.2", "26.1", "26.2", "26.3"] },
    { "id": 16, "tasks": ["26.4"] }
  ]
}
```
