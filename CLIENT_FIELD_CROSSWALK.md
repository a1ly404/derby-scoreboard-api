# Client Field Crosswalk (Basic)

This document maps the client’s requested scoreboard display values against the current `GET /live` response.

Scope is intentionally basic and focused on what is needed for a first pass display.

## 1) Requested fields vs `GET /live`

| Client requested value | Available in `GET /live` | Field(s) |
|---|---|---|
| Period | Yes | `period` |
| Jam | Yes | `jam` |
| Period Clock | Yes | `period_clock_ms` |
| Jam Clock | Yes | `jam_clock_ms` |
| Home Score | Yes | `team1.score` |
| Away Score | Yes | `team2.score` |
| Home Jam Score | Yes | `team1.jam_score` |
| Away Jam Score | Yes | `team2.jam_score` |
| Home PP Timer | Yes (via skater box timer) | `team1.jammer.in_box`, `team1.jammer.box_time_remaining_s` |
| Away PP Timer | Yes (via skater box timer) | `team2.jammer.in_box`, `team2.jammer.box_time_remaining_s` |
| Home Player Tracker (1-5) | Yes | `team1.jammer`, `team1.pivot`, `team1.blocker1`, `team1.blocker2`, `team1.blocker3` |
| Away Player Tracker (1-5) | Yes | `team2.jammer`, `team2.pivot`, `team2.blocker1`, `team2.blocker2`, `team2.blocker3` |

Notes:
- Player tracker rows include skater `name`, `number`, and penalty-box state (`in_box`, `box_time_remaining_s`).
- PP timer can be rendered from jammer box state/timer for each team.

## 2) Key values currently missing from `GET /live`

The following are not currently mapped into `GET /live` and should be added for the production broadcast display:

1. Lead jammer skater (explicit display field)
   - Today, lead can be inferred via `team1.lead` / `team2.lead` plus jammer identity, but there is no explicit top-level “lead jammer skater” value.

2. Timeout state and type
   - Team timeout
   - Official timeout
   - Official review

3. Timeout ownership and counters
   - Which team called timeout/review
   - Team timeouts remaining per team
   - Official review availability/status per team

4. Timeout/review timer behavior
   - Team timeout clock (fixed 60s)
   - Official timeout timing (variable duration)
   - Official review timing (variable duration)

5. Post-timeout to jam-start phase
   - A display flag/timer for the window between timeout end and next jam start.

## 3) Rules/operations notes to confirm with league

- Team timeouts: each team has three total, but event policy should confirm whether tracked per game or displayed per half in this production.
- Official review: one per team per half, and may be retained if successful (once).
- Official timeout and official review durations are not fixed.

These rules are officiating policy context. The API should still expose neutral fields (type, owner, running, remaining, total/used/remaining) so the display can apply event-specific presentation.

## 4) Minimal overview fields for immediate implementation

For the fastest basic display, include this overview set:

- State: `period`, `jam`, `game_state`, `in_jam`, `jam_running`
- Clocks: `period_clock_ms`, `jam_clock_ms`
- Scores: `team1.score`, `team2.score`, `team1.jam_score`, `team2.jam_score`
- Lead and star pass indicators: `team1.lead`, `team2.lead`, `team1.star_pass`, `team2.star_pass`
- Player tracker: all five positions for both teams (name, number, in-box, box timer)
- Timeout package (to add): timeout type, owner, running flag, remaining ms (when fixed), team timeout counts, official review status, post-timeout phase indicator

## 5) Follow-up implementation plan

1. Use `GET /raw` during a live timeout/review sequence to capture exact CRG key names.
2. Add timeout/review fields to `models.py` (`LiveState` and/or `TeamState`).
3. Map those keys in `client.py` field maps.
4. Add tests for team timeout, official timeout, official review, and post-timeout phase.
5. Update display UI to render timeout/review banner and counters.
