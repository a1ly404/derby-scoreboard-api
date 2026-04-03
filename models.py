from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class SkaterPosition(BaseModel):
    name: Optional[str] = None
    number: Optional[str] = None
    in_box: bool = False
    box_entered_at_ms: Optional[int] = Field(
        default=None,
        description=(
            "Unix epoch milliseconds when this skater entered the penalty box. "
            "None when the skater is not in the box. "
            "Overlay usage: elapsed_ms = Date.now() - box_entered_at_ms"
        ),
    )
    box_time_remaining_s: Optional[int] = Field(
        default=None,
        description=(
            "Whole seconds remaining in the 30-second penalty box. "
            "None when the skater is not in the box. 0 when time has expired."
        ),
    )


class TeamState(BaseModel):
    name: Optional[str] = None
    score: Optional[int] = None
    jam_score: Optional[int] = None
    lead: Optional[bool] = None
    display_lead: Optional[bool] = None
    calloff: Optional[bool] = None
    lost: Optional[bool] = None
    star_pass: Optional[bool] = None
    jammer: SkaterPosition = Field(
        default_factory=SkaterPosition,
        description=(
            "The active jammer for this jam. "
            "When star_pass is True this is the original pivot, who received the jammer cover."
        ),
    )
    pivot: SkaterPosition = Field(
        default_factory=SkaterPosition,
        description=(
            "The pivot for this jam. "
            "When star_pass is True this slot holds the original jammer, who has removed their star "
            "and is now skating as a blocker. The pivot label is kept for model simplicity — "
            "consumers should check star_pass to know this skater's effective role is blocker."
        ),
    )
    blocker1: SkaterPosition = Field(default_factory=SkaterPosition)
    blocker2: SkaterPosition = Field(default_factory=SkaterPosition)
    blocker3: SkaterPosition = Field(default_factory=SkaterPosition)


class LiveState(BaseModel):
    connected: bool = False
    period: Optional[int] = None
    jam: Optional[int] = None
    jam_clock_ms: Optional[int] = None
    jam_clock: Optional[str] = None
    period_clock_ms: Optional[int] = None
    period_clock: Optional[str] = None
    jam_running: Optional[bool] = None
    in_jam: Optional[bool] = None
    game_state: Optional[str] = Field(
        default=None,
        description=(
            "Display-oriented game state. Usually mirrors CRG's State field, "
            "but may be synthesized from clock activity for clearer downstream use. "
            'For example, when Clock(Intermission).Running is true this is returned as "Intermission" '
            'even if the raw CRG State still reads "Running".'
        ),
    )
    timeout_type: Optional[str] = Field(
        default=None,
        description=(
            "Normalized timeout/review state. "
            "One of: team_timeout, official_timeout, official_review, timeout, or null. "
            "Resets to null when jam_running is true."
        ),
    )
    timeout_clock_ms: Optional[int] = Field(
        default=None,
        description=(
            "Timeout clock value in milliseconds as reported by CRG Clock(Timeout). "
            "None when no timeout is active."
        ),
    )
    timeout_clock: Optional[str] = None
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
