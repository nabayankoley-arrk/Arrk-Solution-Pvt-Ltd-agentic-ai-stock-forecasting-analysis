"""Assembles the Chat Intent & Routing Subgraph's state graph.

    START -> load_user_memory -> load_conversation_context -> parse_and_route
                                                                    |
                          ,-- tool_call ---------------------------+--> execute_tool_call -\\
                          |                                                                  |
                          |<-------------------------------------------------------------- -/
                          |-- finalize -------> format_conversational_reply -> update_session_context
                          |                                                        -> update_user_memory
                          |                                                        -> build_final_response -> END
                          |-- clarify --------> build_clarification_response -> END
                          `-- out_of_scope ---> build_out_of_scope_response -> END

This is the "Chat Intent & Routing Subgraph — Specification" document's
own graph (parse_and_route as the sole decision-maker; execute_tool_call,
the three terminal builders, format_conversational_reply, and
update_session_context as deterministic steps around it), plus the "User
Memory — Specification (Chat Intent & Routing Subgraph Extension)"
document's two added edges:

    START -> load_user_memory -> parse_and_route
    update_session_context -> update_user_memory -> build_final_response

One deviation from both documents, in one place only: load_conversation_context
is inserted between load_user_memory and parse_and_route. Neither
specification explains how a stateless HTTP endpoint recovers
conversation_history / the previously-resolved ticker across separate
requests using only a session_id -- see that node's own module docstring
for the full reasoning. Every other edge below is exactly as specified.

No validate_input or build_error_response node -- per the base
specification's Architecture section, a chat message is never
structurally "invalid"; nonsense/off-topic input resolves through
parse_and_route's own out-of-scope classification instead.
"""

from langgraph.graph import END, START, StateGraph

from .config import MAX_PARSE_LOOPS
from .nodes.build_clarification_response import build_clarification_response
from .nodes.build_final_response import build_final_response
from .nodes.build_out_of_scope_response import build_out_of_scope_response
from .nodes.execute_tool_call import execute_tool_call
from .nodes.format_conversational_reply import format_conversational_reply
from .nodes.load_conversation_context import load_conversation_context
from .nodes.load_user_memory import load_user_memory
from .nodes.parse_and_route import parse_and_route
from .nodes.update_session_context import update_session_context
from .nodes.update_user_memory import update_user_memory
from .state import ChatIntentRoutingState

_ROUTE_TARGETS = [
    "execute_tool_call",
    "format_conversational_reply",
    "build_clarification_response",
    "build_out_of_scope_response",
]


def route_after_parse_and_route(state: ChatIntentRoutingState) -> str:
    # Loop guard: force clarification once too many agent -> tool -> agent
    # iterations have happened, regardless of what parse_and_route wants
    # to do next -- per the specification, rather than looping indefinitely
    # on an unresolved ambiguity.
    if state.get("requery_count", 0) >= MAX_PARSE_LOOPS:
        return "build_clarification_response"

    routing_decision = state.get("routing_decision")
    if routing_decision == "tool_call":
        return "execute_tool_call"
    if routing_decision == "finalize":
        return "format_conversational_reply"
    if routing_decision == "out_of_scope":
        return "build_out_of_scope_response"
    # "clarify", or anything unexpected -- end the turn with a question
    # rather than guessing.
    return "build_clarification_response"


def build_graph():
    graph = StateGraph(ChatIntentRoutingState)

    graph.add_node("load_user_memory", load_user_memory)
    graph.add_node("load_conversation_context", load_conversation_context)
    graph.add_node("parse_and_route", parse_and_route)
    graph.add_node("execute_tool_call", execute_tool_call)
    graph.add_node("build_clarification_response", build_clarification_response)
    graph.add_node("build_out_of_scope_response", build_out_of_scope_response)
    graph.add_node("format_conversational_reply", format_conversational_reply)
    graph.add_node("update_session_context", update_session_context)
    graph.add_node("update_user_memory", update_user_memory)
    graph.add_node("build_final_response", build_final_response)

    graph.add_edge(START, "load_user_memory")
    graph.add_edge("load_user_memory", "load_conversation_context")
    graph.add_edge("load_conversation_context", "parse_and_route")

    graph.add_conditional_edges("parse_and_route", route_after_parse_and_route, _ROUTE_TARGETS)
    graph.add_edge("execute_tool_call", "parse_and_route")

    graph.add_edge("build_clarification_response", END)
    graph.add_edge("build_out_of_scope_response", END)

    graph.add_edge("format_conversational_reply", "update_session_context")
    graph.add_edge("update_session_context", "update_user_memory")
    graph.add_edge("update_user_memory", "build_final_response")
    graph.add_edge("build_final_response", END)

    return graph.compile()
