"""plan_analysis — picks the pillars and their weights for the horizon.

Reads config.HORIZON_PLAN: short term runs technical and sentiment only,
medium and long term run all three with different weights. Pillars left out
are marked "skipped" in pillar_status, so they read as not planned rather than
as failed. graph.py fans out to the planned pillars only.
"""

from .. import config

ALL_PILLARS = ("technical", "fundamental", "sentiment")


def plan_analysis(state):
    weights = dict(config.HORIZON_PLAN[state["horizon"]])
    skipped = [p for p in ALL_PILLARS if p not in weights]
    return {
        "planned_pillars": [p for p in ALL_PILLARS if p in weights],
        "pillar_weights": weights,
        "pillar_status": {p: "skipped" for p in skipped},
        "errors": {p: None for p in skipped},
    }
