"""reconcile_and_decide — the orchestrator's one LLM step.

Gives the LLM compact digests of the planned pillars, the horizon's weights
and guidance, and the deterministic weighted verdict (_verdict.py) as a
baseline. It either reruns one planned pillar (bounded by
config.MAX_TOOL_LOOPS) or finalizes with the verdict -- direction,
confidence, key drivers, conflicts -- and a short explanation (`reason`,
shown to the user as the narrative).

The LLM's verdict is checked against the baseline in llm_client._parse_decision:
it may lean away from it but not flip bullish to bearish, and cannot claim
high confidence when pillars conflict. When the loop guard trips or the LLM
is unavailable, the baseline verdict is used as-is.
"""

from .. import config
from ..llm_client import get_decision
from ._verdict import pillar_digests, weighted_verdict

_RERUN_TOOL_PILLAR = {"rerun_technical": "technical", "rerun_fundamental": "fundamental", "rerun_sentiment": "sentiment"}


def reconcile_and_decide(state):
    tool_loop_count = state.get("tool_loop_count", 0)
    baseline = weighted_verdict(state)

    if tool_loop_count >= config.MAX_TOOL_LOOPS:
        return {
            "decision": "finalize",
            "selected_tool": None,
            "tool_call_args": {},
            "reason": f"Reached the rerun limit ({config.MAX_TOOL_LOOPS}); using the weighted verdict.",
            "verdict": baseline,
        }

    planned = state.get("planned_pillars") or []
    context = {
        "ticker": state.get("ticker"),
        "horizon": state.get("horizon"),
        "horizon_guidance": config.HORIZON_GUIDANCE[state.get("horizon")],
        "pillar_weights": state.get("pillar_weights") or {},
        "pillars": pillar_digests(state),
        "pillar_status": {p: s for p, s in (state.get("pillar_status") or {}).items() if p in planned},
        "baseline_verdict": baseline,
        "tool_loop_count": tool_loop_count,
        "max_tool_loops": config.MAX_TOOL_LOOPS,
        "enabled_rerun_tools": [t for t in config.ENABLED_RERUN_TOOLS if _RERUN_TOOL_PILLAR.get(t) in planned],
    }
    decision = get_decision(context)
    return {
        "decision": decision["decision"],
        "selected_tool": decision["selected_tool"],
        "tool_call_args": decision["tool_call_args"],
        "reason": decision["reason"],
        "verdict": decision["verdict"],
    }
