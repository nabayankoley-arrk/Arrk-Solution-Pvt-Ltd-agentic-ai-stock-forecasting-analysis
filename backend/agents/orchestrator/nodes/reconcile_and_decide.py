"""reconcile_and_decide — the Orchestrator's one LLM-driven node.

Builds the reconciliation context from the three baseline (or latest
rerun) pillar results -- technical, fundamental, sentiment -- and asks
the LLM Agent (llm_client.get_decision) to decide finalize vs. call_tool
per the specification's "LLM Agent Decision Contract". Two things the
contract entrusts to the LLM are re-checked
deterministically here rather than trusted blindly, since getting either
wrong would silently ship an unreviewed, disagreeing, or incomplete
result:

  1. The MAX_TOOL_LOOPS loop guard -- if tripped, this forces
     decision=finalize/requires_review=True itself rather than asking the
     LLM Agent to notice and honor it.
  2. requires_review being true whenever the pillars disagree or a pillar
     is unhealthy -- the LLM Agent is asked to already set this, but this
     node upgrades False to True if it detects either condition anyway.
"""

from .. import config
from ..llm_client import get_decision

_DIRECTION_PATHS = {
    "technical": ("technical_analysis", "technical_signal", "direction"),
    "fundamental": ("fundamental_analysis", "composite", "direction"),
    "sentiment": ("sentiment_analysis", "direction"),
}


def _pillar_direction(state, pillar):
    value = state.get(_DIRECTION_PATHS[pillar][0])
    for key in _DIRECTION_PATHS[pillar][1:]:
        value = (value or {}).get(key)
    return value


def _pillars_disagree(state):
    directions = {
        direction
        for direction in (_pillar_direction(state, pillar) for pillar in _DIRECTION_PATHS)
        if direction is not None
    }
    return len(directions) > 1


def _has_unresolved_failure(state):
    pillar_status = state.get("pillar_status") or {}
    return any(status != "ok" for status in pillar_status.values())


def reconcile_and_decide(state):
    tool_loop_count = state.get("tool_loop_count", 0)
    loop_guard_tripped = tool_loop_count >= config.MAX_TOOL_LOOPS and not state.get("loop_guard_override")

    if loop_guard_tripped:
        return {
            "decision": "finalize",
            "selected_tool": None,
            "reason": f"loop guard: reached MAX_TOOL_LOOPS ({config.MAX_TOOL_LOOPS}) without agreement",
            "tool_call_args": {},
            "requires_review": True,
            "loop_guard_override": False,
        }

    context = {
        "ticker": state.get("ticker"),
        "horizon": state.get("horizon"),
        "technical_analysis": state.get("technical_analysis"),
        "fundamental_analysis": state.get("fundamental_analysis"),
        "sentiment_analysis": state.get("sentiment_analysis"),
        "pillar_status": state.get("pillar_status") or {},
        "errors": state.get("errors") or {},
        "tool_loop_count": tool_loop_count,
        "max_tool_loops": config.MAX_TOOL_LOOPS,
        "enabled_rerun_tools": config.ENABLED_RERUN_TOOLS,
    }
    decision = get_decision(context)

    requires_review = decision["requires_review"]
    if decision["decision"] == "finalize" and not requires_review:
        if _pillars_disagree(state) or _has_unresolved_failure(state):
            requires_review = True
            note = "(requires_review overridden to true: pillar disagreement or unresolved pillar failure detected)"
            decision["reason"] = f"{decision['reason']} {note}".strip()

    return {
        "decision": decision["decision"],
        "selected_tool": decision["selected_tool"],
        "reason": decision["reason"],
        "tool_call_args": decision["tool_call_args"],
        "requires_review": requires_review,
        "loop_guard_override": False,
    }
