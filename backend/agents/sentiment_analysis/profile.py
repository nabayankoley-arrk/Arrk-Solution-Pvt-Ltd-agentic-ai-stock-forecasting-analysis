"""Builds and validates a document's sentiment profile (prompts.profile_prompt).

build_profile() is the one place a stored summary becomes a profile, called by
nodes/_score_helpers.py when a document has no current profile. The model's
JSON is normalised rather than trusted: unknown labels fail the profile,
unknown themes and stances are dropped, lists are capped, and a quote that does
not appear in the summary is discarded, so a profile never claims more than the
summary holds.
"""

from . import prompts

_MAX_LIST = 3


class ProfileError(ValueError):
    """The model's reply could not be turned into a valid profile."""


def _text(value, limit=400):
    return str(value).strip()[:limit] if value else ""


def _points(values, limit=_MAX_LIST):
    return [p for p in (_text(v, 300) for v in (values or []) if isinstance(v, str)) if p][:limit]


def _stories(values, article_count):
    """News only: [{"article": 1-based number, "summary"}], each pointing at a
    real article, at most once, capped at prompts.MAX_STORIES."""
    stories, seen = [], set()
    for entry in values or []:
        if not isinstance(entry, dict):
            continue
        number, text = entry.get("article"), _text(entry.get("summary"), 400)
        if isinstance(number, str) and number.strip("[] ").isdigit():
            number = int(number.strip("[] "))
        if isinstance(number, int) and 1 <= number <= article_count and number not in seen and text:
            seen.add(number)
            stories.append({"article": number, "summary": text})
    return stories[: prompts.MAX_STORIES]


def normalise(raw, summary="", article_count=None):
    """A validated profile dict from the model's parsed JSON, or ProfileError.
    article_count is set for news only, whose profile also carries "stories"."""
    if not isinstance(raw, dict):
        raise ProfileError(f"expected a JSON object, got {type(raw).__name__}")
    label = raw.get("label")
    if label not in prompts.LABELS:
        raise ProfileError(f"unexpected label: {label!r}")

    tone = raw.get("management_tone")
    guidance = raw.get("guidance")
    themes, seen = [], set()
    for entry in raw.get("themes") or []:
        if not isinstance(entry, dict):
            continue
        theme, stance = entry.get("theme"), entry.get("stance")
        if theme in prompts.THEMES and stance in prompts.STANCES and theme not in seen:
            seen.add(theme)
            themes.append({"theme": theme, "stance": stance, "point": _text(entry.get("point"), 300)})

    lowered_summary = (summary or "").lower()
    quotes = [q for q in _points(raw.get("notable_quotes")) if q.strip('"“” ').lower() in lowered_summary]

    profile = {
        "label": label,
        "management_tone": tone if tone in prompts.MANAGEMENT_TONES else None,
        "guidance": guidance if guidance in prompts.GUIDANCE else "not_given",
        "rationale": _text(raw.get("rationale")),
        "themes": themes,
        "positives": _points(raw.get("positives")),
        "concerns": _points(raw.get("concerns")),
        "notable_quotes": quotes,
    }
    if article_count is not None:
        profile["stories"] = _stories(raw.get("stories"), article_count)
    return profile


def build_profile(ask, report_type, company, report_name, filed_on, summary, article_count=None):
    """ask(system_prompt, user_prompt) -> the model's reply text. Returns the
    normalised profile; raises ProfileError when the reply is unusable.
    article_count: news only, the number of articles in `summary`."""
    from agents.orchestrator.llm_client import extract_json_object  # lazy: see _score_helpers' docstring

    reply = ask(
        prompts.profile_prompt(report_type),
        prompts.profile_user_prompt(report_type, company, report_name, filed_on, summary),
    )
    try:
        parsed = extract_json_object(reply)
    except Exception as exc:
        raise ProfileError(str(exc)[:200]) from exc
    return normalise(parsed, summary, article_count)
