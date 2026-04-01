from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class SkaterPosition(BaseModel):
    name: Optional[str] = None
    number: Optional[str] = None
    in_box: bool = False
    box_time_remaining_ms: Optional[int] = None
    """Milliseconds remaining in this skater's penalty, counting jam time only.
    None when the skater is not in the box.  Starts at 30_000 on box entry and
    counts down only while jam_running is True.  Clamped to 0 — will not go
    negative.  Assumes a single 30-second penalty; for stacking, a future
    version can multiply by penalty count before this is computed.
    """


class TeamState(BaseModel):
    name: Optional[str] = None
    score: Optional[int] = None
    jam_score: Optional[int] = None
    lead: Optional[bool] = None
    display_lead: Optional[bool] = None
    calloff: Optional[bool] = None
    lost: Optional[bool] = None
    star_pass: Optional[bool] = None
    jammer: SkaterPosition = Field(default_factory=SkaterPosition)
    pivot: SkaterPosition = Field(default_factory=SkaterPosition)
    blocker1: SkaterPosition = Field(default_factory=SkaterPosition)
    blocker2: SkaterPosition = Field(default_factory=SkaterPosition)
    blocker3: SkaterPosition = Field(default_factory=SkaterPosition)


class LiveState(BaseModel):
    connected: bool = False
    period: Optional[int] = None
    jam: Optional[int] = None
    jam_clock_ms: Optional[int] = None
    period_clock_ms: Optional[int] = None
    jam_running: Optional[bool] = None
    in_jam: Optional[bool] = None
    game_state: Optional[str] = None
    state_age_seconds: Optional[float] = None
    team1: TeamState = Field(default_factory=TeamState)
    team2: TeamState = Field(default_factory=TeamState)


class HealthState(BaseModel):
    connected: bool
    scoreboard_version: Optional[str] = None
    seconds_since_update: Optional[float] = None
    """Seconds elapsed since the last state update was received from the scoreboard.
    None means no update has ever been received (newly connected or never connected).
    A large value while connected=True indicates the scoreboard may be frozen.
    """
