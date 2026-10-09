# Data check

- Tracking files: 122; plays in plays.csv: 8557
- Distinct events: autoevent_ballsnap, autoevent_passforward, autoevent_passinterrupted, ball_snap, dropped_pass, first_contact, fumble, fumble_offense_recovered, handoff, huddle_break_offense, lateral, line_set, man_in_motion, out_of_bounds, pass_arrived, pass_forward, pass_outcome_caught, pass_outcome_incomplete, pass_tipped, penalty_flag, play_action, qb_sack, qb_strip_sack, run, shift, tackle
- Last event per play (counts): nan=8101, pass_arrived=308, autoevent_passinterrupted=94, pass_outcome_caught=21, pass_outcome_incomplete=19, pass_tipped=4, first_contact=4, autoevent_passforward=2, pass_forward=2, dropped_pass=1, out_of_bounds=1
- Tracking ends ~0.5 s after the throw on pass plays (no catch / tackle frames).
- Missing pff_nflIdBlockedPlayer (Pass Block rows): 3.3%
- Missing pff_positionLinedUp (Pass Block rows): 0.0%

## Unresolved plays (24)

| gameId | playId | reason |
|---|---|---|
| 2021091200 | 4367 | no snap event |
| 2021091202 | 3606 | no snap event |
| 2021091206 | 1296 | no snap event |
| 2021091904 | 1614 | no snap event |
| 2021091907 | 1836 | no snap event |
| 2021091907 | 1857 | no snap event |
| 2021091909 | 3565 | no snap event |
| 2021091912 | 1868 | no snap event |
| 2021092605 | 1911 | no snap event |
| 2021092611 | 1641 | no snap event |
| 2021100302 | 775 | no snap event |
| 2021100302 | 3688 | no snap event |
| 2021100307 | 4668 | no snap event |
| 2021100308 | 4330 | no snap event |
| 2021100313 | 1878 | no snap event |
| 2021100700 | 2963 | no snap event |
| 2021101004 | 3595 | no snap event |
| 2021101004 | 3861 | no snap event |
| 2021101706 | 1932 | no snap event |
| 2021101800 | 3505 | no snap event |
| 2021102405 | 4101 | no snap event |
| 2021102408 | 1872 | no snap event |
| 2021102410 | 3833 | no snap event |
| 2021103101 | 4401 | no snap event |
