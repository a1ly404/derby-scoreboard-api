from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


class TeamState(BaseModel):
    name: Optional[str] = None
    score: Optional[int] = None
    jam_score: Optional[int] = None
    jammer: Optional[str] = None
    jammer_number: Optional[str] = None
    lead: Optional[bool] = None
    display_lead: Optional[bool] = None
    calloff: Optional[bool] = None
    lost: Optional[bool] = None
    star_pass: Optional[bool] = None


class LiveState(BaseModel):
    period: Optional[int] = None
    jam: Optional[int] = None
    jam_clock_ms: Optional[int] = None
    period_clock_ms: Optional[int] = None
    jam_running: Optional[bool] = None
    in_jam: Optional[bool] = None
    game_state: Optional[str] = None
    state_age_seconds: Optional[float] = None
    team1: TeamState = TeamState()
    team2: TeamState = TeamState()


class HealthState(BaseModel):
    connected: bool
    scoreboard_version: Optional[str] = None
    seconds_since_update: Optional[float] = None
    """Seconds elapsed since the last state update was received from the scoreboard.
    None means no update has ever been received (newly connected or never connected).
    A large value while connected=True indicates the scoreboard may be frozen.
    """
