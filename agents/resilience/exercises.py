"""The three supported exercises. Nothing else is accepted: no general scenario generation.

Each exercise is a dormant `Scenario` node in the graph; its `DISABLES` edges are the initial failures and its
`duration_hours` is the exercise window. A closure or grid outage disables assets for the window; a regional
loss destroys them (continuity options may relocate service but never rebuild the asset).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from agents.resilience.network import Network

EventKind = Literal["closure", "power_outage", "regional_loss"]
HOURS_PER_DAY = 24.0


@dataclass(frozen=True)
class Exercise:
    scenario_id: str
    title: str
    prompt: str  # the suggestion shown in the chat panel
    kind: EventKind
    hours: float  # exercise window = the Scenario's duration_hours

    @property
    def destroys(self) -> bool:
        return self.kind == "regional_loss"

    @property
    def days(self) -> int:
        return int(-(-self.hours // HOURS_PER_DAY))


EXERCISES: dict[str, Exercise] = {e.scenario_id: e for e in (
    Exercise("scenario:strait_closure", "Dover Strait maritime closure",
             "Close the Dover Strait to shipping for 72 hours. What breaks, and how do we recover?",
             "closure", 72.0),
    Exercise("scenario:kent_power", "Kent-wide grid outage",
             "All ten Kent grid supplies fail for 48 hours. What breaks, and how do we recover?",
             "power_outage", 48.0),
    Exercise("scenario:london_loss", "London/Croydon critical infrastructure loss",
             "London and Croydon lose their critical infrastructure for 168 hours. What breaks, and how do we recover?",
             "regional_loss", 168.0),
)}


# Free-text questions are matched to an exercise by these cues (deterministic, no model).
CUES: dict[str, tuple[tuple[str, int], ...]] = {
    "scenario:strait_closure": (("strait", 3), ("shipping", 2), ("maritime", 2), ("channel", 2), ("sea", 1),
                                ("ferry", 2), ("ferries", 2), ("vessel", 1), ("ship", 1), ("dover", 1),
                                ("blockade", 2), ("closure", 1), ("closes", 1), ("closed", 1)),
    "scenario:kent_power": (("kent", 3), ("grid", 3), ("power", 2), ("electric", 2), ("blackout", 3),
                            ("outage", 2), ("substation", 2), ("energy", 1)),
    "scenario:london_loss": (("london", 3), ("croydon", 3), ("capital", 1), ("city", 1), ("destroyed", 1),
                             ("infrastructure", 1), ("catastroph", 2), ("attack", 1)),
}
PLACES: dict[str, tuple[str, ...]] = {  # places that pin a question to one exercise's geography
    "scenario:strait_closure": ("strait", "channel"),
    "scenario:kent_power": ("kent",),
    "scenario:london_loss": ("london", "croydon"),
}
NO_MATCH_REPLY = ("I could not tie that to a disruption in the London–Dover–Paris corridor graph. Describe an "
                  "event affecting a crossing, a power network or a city in the corridor, or start from one of "
                  "the suggestions.")


def match_question(text: str) -> Exercise | None:
    """The exercise a free-text question most clearly describes, or None when nothing (or a tie) matches."""
    low = text.lower()
    scores = {sid: sum(w for cue, w in cues if cue in low) for sid, cues in CUES.items()}
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    if ranked[0][1] == 0 or ranked[0][1] == ranked[1][1]:
        return None
    best = ranked[0][0]
    named = {sid for sid, places in PLACES.items() if any(p in low for p in places)}
    if named and best not in named:  # e.g. "London grid outage" is not the Kent outage: do not pretend it is
        return None
    return EXERCISES[best]


class UnsupportedExercise(ValueError):
    pass


def get_exercise(scenario_id: str) -> Exercise:
    try:
        return EXERCISES[scenario_id]
    except KeyError as exc:
        raise UnsupportedExercise(
            f"{scenario_id!r} is not a supported exercise; choose one of {sorted(EXERCISES)}") from exc


def targets(net: Network, ex: Exercise) -> tuple[str, ...]:
    """Initial failures read from the graph, after checking the Scenario still matches this definition."""
    scenario = net.entity(ex.scenario_id)
    if scenario.label != "Scenario" or scenario.num("duration_hours") != ex.hours:
        raise UnsupportedExercise(f"{ex.scenario_id} in the graph no longer matches the {ex.hours:g}-hour exercise")
    found = net.disables.get(ex.scenario_id, ())
    if not found:
        raise UnsupportedExercise(f"{ex.scenario_id} disables nothing in this graph")
    return found


def down_at(ex: Exercise, initial: frozenset[str], t: float) -> frozenset[str]:
    """Physically unavailable assets at hour t: destroyed ones stay down; others reopen after the window."""
    return initial if ex.destroys or t < ex.hours else frozenset()
