"""Tunable constants for the User Memory extension.

The specification names two configurable parameters (MAX_WATCHLIST_SIZE,
MEMORY_ENABLED) with no numeric/boolean default given -- these are read
from the environment below, falling back to this implementation's own
default (not a value taken from the specification itself) when unset.
"""

import os


def _env_int(name, default):
    value = os.environ.get(name)
    return int(value) if value else default


def _env_bool(name, default):
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


# --- update_user_memory: watchlist cap ---
MAX_WATCHLIST_SIZE = _env_int("MAX_WATCHLIST_SIZE", 10)

# --- load_user_memory / update_user_memory: on/off switch ---
# When False, load_user_memory returns an empty memory object regardless
# of what's stored (so parse_and_route behaves exactly as the base
# subgraph without this extension) and update_user_memory no-ops --
# letting the extension be disabled without changing the base subgraph,
# per the specification's Architecture section.
MEMORY_ENABLED = _env_bool("MEMORY_ENABLED", True)
