# Requirements Document

## Introduction

The Pass Protection Error Finder is a web application for NFL coaches that detects and flags errors in pass protection (offense) and pass rush (defense) on dropback pass plays. It uses the NFL Big Data Bowl 2023 dataset (2021 season, Weeks 1-8, 122 games). Every flag links to an animated field replay drawn as dots on a field, with the involved player highlighted and the error moment marked on a timeline. A flag without a working replay is not considered complete.

The tool operates in two team modes: "My team" (self-scout, ranking recurring mistakes by frequency and cost) and "Opponent" (game planning, surfacing weaknesses to attack). Errors are reported across three confidence levels: Confirmed (recorded in data), Likely (rule-based), and Possible (model-based). Flags are grouped into recurring patterns so coaches distinguish noise from coaching points.

Broadcaster mode, live feeds, coverage errors by defensive backs, tackling/pursuit analysis, user accounts, and video integration are out of scope. Detection outputs are designed to be reusable for broadcaster mode later.

## Glossary

- **System**: The complete Pass Protection Error Finder application (backend and frontend).
- **Data_Pipeline**: The backend component that validates raw data, converts tracking CSVs to Parquet, normalizes coordinates, derives measurements, and persists processed data.
- **Detection_Engine**: The backend component that produces flags across the three confidence levels.
- **Pattern_Engine**: The backend component that groups flags into ranked recurring patterns.
- **Cost_Engine**: The backend component that assigns an expected-points cost to each flag using nflverse play-by-play EPA.
- **API**: The FastAPI service that exposes flags, patterns, plays, players, and tracking data to the frontend.
- **Play_Viewer**: The frontend component that renders the animated field replay on an HTML Canvas.
- **Alerts_List**: The frontend screen that lists all flags for the selected team and games.
- **Patterns_Screen**: The frontend screen that lists ranked recurring patterns with Self-scout and Opponent tabs.
- **Player_Page**: The frontend screen that shows a single player's flags, patterns, and key metrics.
- **Team_Selector**: The frontend control that chooses between "My team" and "Opponent" mode, stored in the URL.
- **Flag**: A single detected error carrying gameId, playId, error-moment frameId, involved nflIds, team, error type, confidence level, a one-sentence plain-English explanation, and (where available) an expected-points cost.
- **Confidence_Level**: One of three values — Confirmed (Level 1), Likely (Level 2), Possible (Level 3).
- **Dropback_Pass_Play**: A play where dropBackType indicates a dropback pass.
- **Snap_Frame**: The tracking frame at which the ball is snapped, detected from snap event variants.
- **End_Of_Dropback_Frame**: The tracking frame marking the end of the dropback, detected from pass/sack/scramble event variants.
- **Line_Of_Scrimmage**: The normalized ball x-coordinate at the Snap_Frame.
- **Normalized_Coordinates**: Tracking coordinates transformed so offense always moves toward increasing x.
- **Engagement**: A period where a blocker and a rusher are within 1.5 yards for at least 3 consecutive frames.
- **Pressure**: A play state where any defender has pff_hit, pff_hurry, or pff_sack equal to 1.
- **Pocket**: The polygon formed by the convex hull of the pass blockers and the QB positions at a given frame; Pocket area is the shoelace area of that convex hull.
- **Blocker_Set_Point**: The frame at which a blocker's forward velocity stops after the snap, used as the reference for depth-conceded measurements.
- **Sample_Size**: The number of opportunities for an error type within a group, used as the denominator for a pattern or player-level statistic (for example, the player's pass-block reps in that situation, stunts faced, or the defense's pass-rush snaps for the lost escape lane).
- **Opportunity**: A single chance for a given error type to occur within a group, counted so that rate equals count divided by opportunities.
- **Error_Frame**: The frameId recorded on a Flag that marks the error moment used by the Play_Viewer timeline.
- **EPA**: Expected Points Added, sourced from nflverse play-by-play data.
- **Thresholds_Config**: The file config/thresholds.yaml containing all tunable numeric thresholds with explanatory comments, including pattern_min_opportunities (default 10), pressure_spike_delta (default 0.25), pressure_spike_window (default 5 frames), free_rusher_qb_yd, and set_point_fallback_seconds (default 0.5).

## Requirements

### Requirement 1: Monorepo and Project Structure

**User Story:** As a developer, I want a well-organized monorepo with a reproducible setup, so that the tool builds and runs on a fresh clone.

#### Acceptance Criteria

1. THE System SHALL organize code as a monorepo at the workspace root containing a backend directory for Python code and a frontend directory for the React, TypeScript, and Vite application.
2. THE Data_Pipeline SHALL read raw input from the data/raw directory and write processed Parquet output to the data/processed directory.
3. THE System SHALL provide a `make data` command that runs the full data pipeline and a `make dev` command that starts the development servers.
4. WHEN `make data` is run on a fresh clone followed by `make dev`, THE System SHALL complete both without manual intervention beyond documented prerequisites.
5. THE System SHALL store all tunable numeric thresholds in config/thresholds.yaml with explanatory comments, and the code SHALL read thresholds from that file rather than embedding numeric literals.
6. THE System SHALL use Python 3.11 or later, Polars, DuckDB, Parquet, FastAPI, React with TypeScript and Vite, HTML Canvas for rendering, scikit-learn, and LightGBM.

### Requirement 2: Phase 0 Data Check

**User Story:** As a developer, I want a documented data check before building, so that I understand event semantics and data quality.

#### Acceptance Criteria

1. THE Data_Pipeline SHALL compute the distinct event values present in the tracking data and the last event recorded per play.
2. THE Data_Pipeline SHALL detect the Snap_Frame handling both manual and automatic event variants, including ball_snap and autoevent_ballsnap.
3. THE Data_Pipeline SHALL detect the End_Of_Dropback_Frame handling pass_forward, autoevent_passforward, sack, strip-sack, and scramble event variants.
4. THE Data_Pipeline SHALL compute the missing-value rates for pff_nflIdBlockedPlayer, pff_positionLinedUp, and the tracking coordinate and motion fields.
5. THE Data_Pipeline SHALL convert the tracking CSV files to Parquet one time, and the API SHALL query the Parquet data with DuckDB or Polars rather than loading all CSV files per request.
6. THE Data_Pipeline SHALL write the data check findings to reports/data_check.md.

### Requirement 3: Preprocessing and Normalization

**User Story:** As a developer, I want normalized, enriched tracking data, so that downstream measurements are direction-independent and role-aware.

#### Acceptance Criteria

1. WHERE playDirection equals left, THE Data_Pipeline SHALL set x to 120 minus x, y to 53.3 minus y, o to (o plus 180) modulo 360, and dir to (dir plus 180) modulo 360.
2. THE Data_Pipeline SHALL define the Line_Of_Scrimmage as the normalized ball x-coordinate at the Snap_Frame.
3. THE Data_Pipeline SHALL compute time since snap for each frame as (frameId minus the Snap_Frame frameId) divided by 10.
4. THE Data_Pipeline SHALL join the PFF role and alignment fields onto every tracking row by gameId, playId, and nflId.
5. WHERE an nflId value is NA in a tracking row, THE Data_Pipeline SHALL treat that row as the ball row with team equal to football.

### Requirement 4: Derived Measurements

**User Story:** As a developer, I want a reusable, tested feature module, so that detection and models share consistent measurements.

#### Acceptance Criteria

1. THE Data_Pipeline SHALL compute per-play measurements including time to throw, counts of rushers and blockers by role, Pressure, Pocket area per frame, and Pocket shrink rate, where Pocket area is computed by first forming the convex hull of the pass-blocker positions together with the QB positions and then applying the shoelace area formula to that convex hull.
2. THE Data_Pipeline SHALL compute per-rusher get-off time as the time the rusher's speed first exceeds the configured get-off speed threshold defaulting to 2.0 yards per second.
3. THE Data_Pipeline SHALL detect each Engagement as a blocker and rusher within 1.5 yards for at least 3 consecutive frames, recording start and end frames, and SHALL cross-check against pff_nflIdBlockedPlayer while deriving the Engagement from tracking.
4. THE Data_Pipeline SHALL compute depth conceded for each blocker at 1.0, 1.5, 2.0, and 2.5 seconds relative to the blocker set point.
5. THE Data_Pipeline SHALL compute rush path attributes including inside or outside lateral direction, speed at first contact, and whether the rusher crossed paths with another rusher.
6. THE Data_Pipeline SHALL compute each rusher's closest approach distance to the QB and the time of that closest approach.
7. THE Data_Pipeline SHALL include unit tests for the geometry operations including distance, crossing detection, polygon area, and direction flip, using hand-made examples, and SHALL include a convex-hull-area test that supplies unordered input points whose correct area is known and asserts the computed Pocket area equals that known value.
8. THE Data_Pipeline SHALL set the Blocker_Set_Point for each blocker to the velocity-stop frame, defined as the frame within 1.0 second of the Snap_Frame at which the blocker's forward velocity first stops.
9. IF no clear velocity stop occurs within 1.0 second of the Snap_Frame, THEN THE Data_Pipeline SHALL set the Blocker_Set_Point to the blocker's position at set_point_fallback_seconds (default 0.5 second) after the Snap_Frame and SHALL record that the fallback was used.

### Requirement 5: Level 1 Confirmed Flags

**User Story:** As a coach, I want errors recorded directly in the data flagged, so that I have an authoritative answer key with no modeling.

#### Acceptance Criteria

1. WHEN a play has a foulName and matching foulNFLId, THE Detection_Engine SHALL emit a Confirmed Flag for the penalty attributed to the identified player with the Error_Frame set to the Snap_Frame.
2. WHEN a blocker has pff_sackAllowed, pff_hitAllowed, or pff_hurryAllowed equal to 1, THE Detection_Engine SHALL emit a Confirmed Flag attributed to that blocker with the Error_Frame set to the frame at which the rusher the blocker was engaged with, or the rusher identified by pff_nflIdBlockedPlayer, makes his closest approach to the QB.
3. WHEN a blocker has pff_beatenByDefender equal to 1, THE Detection_Engine SHALL emit a Confirmed Flag indicating the blocker was beaten with the Error_Frame set to the frame at which that rusher passes the blocker.
4. IF the frame at which the rusher passes the blocker cannot be determined for a pff_beatenByDefender Flag, THEN THE Detection_Engine SHALL set the Error_Frame to the frame of that rusher's closest approach to the QB.
5. THE Detection_Engine SHALL produce Level 1 Flags using recorded data only, without any modeling.

### Requirement 6: Level 2 Likely Flags

**User Story:** As a coach, I want rule-based likely errors flagged, so that I can review film where the data strongly suggests a mistake.

#### Acceptance Criteria

1. WHEN the blocker count is greater than or equal to the rusher count and a rusher has no Engagement before getting within 3 yards of the QB or before the throw, THE Detection_Engine SHALL emit a Likely Flag for a free rusher with the error moment set to the frame the rusher passes the line of blockers.
2. WHEN two blockers engage the same rusher while another rusher is free, THE Detection_Engine SHALL emit a Likely Flag for a wasted double team.
3. WHEN two rushers' paths cross within 2.0 seconds, no SW block type is recorded, neither blocker moved to the other rusher, and a rusher ends free or causes Pressure, THE Detection_Engine SHALL emit a Likely Flag for a stunt not handled.
4. WHEN passResult equals R and at the frame the QB crosses outside the tackle box both edge rushers are inside the QB, THE Detection_Engine SHALL emit a Likely Flag for a lost escape lane defensive error.
5. THE Detection_Engine SHALL label every Level 2 Flag with "Likely: check the film" and SHALL implement each rule as explicit, readable code using thresholds from Thresholds_Config.
6. WHERE a Level 2 rule uses a blocker count, THE Detection_Engine SHALL count only pass blockers whose block type is not CH, SR, or NB.
7. THE Data_Pipeline SHALL calibrate Level 2 thresholds on training games only, report the precision and recall of each rule versus PFF labels on held-out games only, and write the results to reports/level2_calibration.md.
8. WHERE the lost escape lane rule has no PFF label that can confirm it, THE Data_Pipeline SHALL record "no answer key" for that rule in reports/level2_calibration.md, and THE Detection_Engine SHALL validate that rule by manual review of a sample of flagged plays instead of against PFF labels.

### Requirement 7: Level 3 Possible Flags and Models

**User Story:** As a coach, I want model-based possible errors flagged, so that I can review reps that are worse than expected.

#### Acceptance Criteria

1. THE Detection_Engine SHALL train an expected-rep model that predicts depth conceded at 1.5 seconds and the probability of being beaten by 2.5 seconds per Engagement using alignments, player history, rusher and blocker counts, and down and distance.
2. THE Detection_Engine SHALL first establish a baseline of situational averages for the expected-rep model before training a gradient-boosted model, and SHALL emit a Possible Flag when a rep is far worse than predicted.
3. THE Detection_Engine SHALL train a pressure-probability model that estimates per frame the chance the play ends in Pressure from the positions and speeds of rushers, blockers, and the QB, trained on PFF hit, hurry, and sack labels.
4. WHEN the pressure probability rises by at least pressure_spike_delta (default 0.25) within a pressure_spike_window of 5 frames, THE Detection_Engine SHALL emit a Possible Flag and attribute the spike to the blocker nearest the causing rusher.
5. THE Detection_Engine SHALL label every Level 3 Flag with "Possible: film to review".
6. THE Detection_Engine SHALL split train and test data by game and SHALL NOT split by random frames or plays.
7. THE Detection_Engine SHALL compute player-history features for the Level 3 models from training games only or by leave-one-game-out, so that no feature for a play uses data from that play's own held-out game.
8. WHERE a player has few reps, THE Detection_Engine SHALL shrink that player's history toward position averages.
9. THE Detection_Engine SHALL track rep counts and SHALL NOT present a player-level statistic without its Sample_Size.
10. THE Detection_Engine SHALL report AUC and a calibration plot for the pressure model and error for the depth model on held-out games, and SHALL write the results to reports/models.md.

### Requirement 8: Flag Content and Expected-Points Cost

**User Story:** As a coach, I want every flag to carry complete, readable context and a cost, so that I can prioritize what matters.

#### Acceptance Criteria

1. THE Detection_Engine SHALL include on every Flag the gameId, playId, the frameId of the error moment, the involved nflIds, the team, the error type, the Confidence_Level, and a one-sentence plain-English explanation.
2. THE Cost_Engine SHALL assign each Flag an expected-points cost using nflverse play-by-play EPA, expressed from the perspective of the team charged with the Flag, flipping the EPA sign for defensive errors.
3. WHEN a play has multiple Flags, THE Cost_Engine SHALL share the play's EPA across those Flags by an equal split rather than assigning each Flag the full play EPA.
4. THE Cost_Engine SHALL auto-download nflverse play-by-play EPA with local caching.
5. IF the EPA source is offline, THEN THE Cost_Engine SHALL degrade gracefully and still produce Flags without the cost value.
6. IF a Flag's cost is missing, THEN THE Pattern_Engine SHALL rank using count instead of cost, and THE Alerts_List SHALL show "cost unavailable" rather than failing.
7. THE Cost_Engine SHALL merge the dataset gameId and playId to the nflverse old_game_id and play_id.
8. WHERE cost is displayed, THE System SHALL label the value as "play EPA (shared)" rather than as the cost of the error itself.

### Requirement 9: Patterns

**User Story:** As a coach, I want recurring errors grouped into ranked patterns, so that I can separate noise from coaching points.

#### Acceptance Criteria

1. THE Pattern_Engine SHALL group Flags into patterns by player, error type, situation including down, distance band, field zone, and score state, opponent alignment and rush type, and protection features including rusher count, stunts, and play action.
2. THE Pattern_Engine SHALL define the Sample_Size of a pattern as the number of opportunities for that error type within that group, such as the player's pass-block reps in that situation, the stunts faced, or the defense's pass-rush snaps for the lost escape lane.
3. THE Pattern_Engine SHALL compute each pattern's rate as count divided by opportunities and SHALL compute the 90% interval as the Wilson 90% interval from count and opportunities.
4. THE Pattern_Engine SHALL show for each pattern the count, the rate, the Sample_Size, and the Wilson 90% interval.
5. WHERE a pattern has fewer than pattern_min_opportunities opportunities (default 10, stored in Thresholds_Config), THE Pattern_Engine SHALL hide that pattern.
6. THE Pattern_Engine SHALL rank patterns by frequency multiplied by average cost.

### Requirement 10: Team Selector and Screens

**User Story:** As a coach, I want to switch between self-scout and opponent perspectives, so that the whole tool reflects the chosen team.

#### Acceptance Criteria

1. THE Team_Selector SHALL let the user choose a "my team" team abbreviation and an opponent team abbreviation, both drawn from games.csv, SHALL appear at the top of the application, and SHALL store my-team, opponent, and mode in the URL.
2. WHILE the Team_Selector is in the default self mode, THE System SHALL show the selected my-team's own errors.
3. WHILE the Team_Selector is in opponent mode, THE System SHALL show the opponent's errors.
4. WHEN the selected teams, mode, or game set changes, THE System SHALL scope the Alerts_List, Patterns_Screen, and Player_Page to the resulting team and those games.

### Requirement 11: Alerts List

**User Story:** As a coach, I want a filterable list of all flags, so that I can jump to the plays that matter.

#### Acceptance Criteria

1. THE Alerts_List SHALL display all Flags for the selected team and games.
2. THE Alerts_List SHALL filter Flags by Confidence_Level, error type, player, week, and situation.
3. WHEN a coach clicks a Flag in the Alerts_List, THE Play_Viewer SHALL open at the Flag's error-moment frame.

### Requirement 12: Patterns Screen

**User Story:** As a coach, I want ranked patterns separated by perspective, so that I can plan self-scout and opponent work distinctly.

#### Acceptance Criteria

1. THE Patterns_Screen SHALL display ranked patterns with a Self-scout tab and an Opponent tab.
2. WHEN a coach selects a pattern, THE Patterns_Screen SHALL link to the plays belonging to that pattern.

### Requirement 13: Play Viewer

**User Story:** As a coach, I want a smooth animated replay with the error moment and player marked, so that I can see exactly what happened.

#### Acceptance Criteria

1. THE Play_Viewer SHALL render on an HTML Canvas a field with yard lines, the Line_Of_Scrimmage, and the first-down line.
2. THE Play_Viewer SHALL draw player dots colored by team with jersey numbers and SHALL draw the ball separately.
3. THE Play_Viewer SHALL provide play and pause controls, speed selection of 0.25x, 0.5x, and 1x, a frame scrubber, and keyboard controls to step forward and backward.
4. THE Play_Viewer SHALL show short 1-second trails with a toggle to show the full path.
5. THE Play_Viewer SHALL draw a Pocket outline around the QB.
6. THE Play_Viewer SHALL show a timeline under the field with event markers for snap, throw, and sack, and Flag markers colored by Confidence_Level.
7. THE Play_Viewer SHALL draw a ring around flagged players, and WHEN a coach clicks a player dot, THE Play_Viewer SHALL show that player's role, alignment, and stats for that play.
8. THE Play_Viewer SHALL show a play header with the teams, quarter, clock, down and distance, result, coverage, and playDescription.
9. THE Play_Viewer SHALL render smoothly at 10 frames per second with 23 moving objects.

### Requirement 14: Player Page

**User Story:** As a coach, I want a per-player view with metrics and samples, so that I can evaluate a player fairly.

#### Acceptance Criteria

1. THE Player_Page SHALL display the player's Flags and patterns.
2. THE Player_Page SHALL display key metrics including get-off time, time to pressure, depth conceded, and win rate by rush type.
3. THE Player_Page SHALL compute time to pressure as the time from the Snap_Frame to the first frame at which the rusher is within free_rusher_qb_yd of the QB.
4. THE Player_Page SHALL compute win rate by rush type as the share of engagements in which the rusher passed the blocker or reached free_rusher_qb_yd of the QB within 2.5 seconds, grouped by rush lateral direction of inside or outside.
5. THE Player_Page SHALL display every player-level metric together with its Sample_Size.

### Requirement 15: Limitations Disclosure

**User Story:** As a coach, I want to understand what the tool cannot tell me, so that I interpret flags responsibly.

#### Acceptance Criteria

1. THE System SHALL provide a "What this tool can't tell you" note reachable from every screen.
2. THE "What this tool can't tell you" note SHALL state that the play call is unknown so an error may be design rather than player, that only pass plays are covered with no run blocking, that tracking ends around the throw, and that eight weeks produces small samples.

### Requirement 16: Phased Delivery and Review Gates

**User Story:** As a stakeholder, I want work ordered into reviewable phases, so that I can stop and review after each phase.

#### Acceptance Criteria

1. THE System SHALL organize implementation into Phases 0 through 5, ordered and grouped so a review gate occurs after each phase.
2. THE System SHALL include pytest backend tests and a small set of frontend component tests.
3. THE System SHALL exclude live feeds, broadcaster mode, coverage errors by defensive backs, tackling and pursuit analysis, user accounts and authentication, and video integration from the delivered scope.
4. WHERE a detection output is produced, THE System SHALL structure that output to be reusable by a future broadcaster mode.
