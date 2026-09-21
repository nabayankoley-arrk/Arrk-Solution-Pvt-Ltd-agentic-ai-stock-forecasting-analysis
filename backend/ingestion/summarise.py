"""Turn an extracted filing into a short summary, via the Claude API.

Streaming is used because the input is long -- a large annual report runs to
several hundred thousand tokens, and a non-streaming request that size risks
an HTTP timeout before the first byte.

Effort defaults to "low". Condensing a document into a dozen lines is a
reading task rather than a reasoning one, and low effort keeps a twenty-company
run affordable. Raise it with --effort if the summaries come back thin.
"""

import anthropic

MODEL = "claude-opus-5"
# A short summary, as asked for. This is a ceiling, not a target.
MAX_SUMMARY_TOKENS = 1200
DEFAULT_EFFORT = "low"

DOCUMENT_LABELS = {
    "AR": "annual report",
    "TR": "earnings or AGM call transcript",
}

SYSTEM = """You summarise filings by Indian listed companies for an equity research system.

Write a short, factual summary that an analyst can read in under a minute:

- Open with one sentence naming the company, the document and the period it covers.
- Then five to eight bullets covering, where the document supports them:
  headline financials with the actual figures, segment or business performance,
  margin and cost movements, balance sheet or cash flow changes, management's
  stated outlook and guidance, and any risk, litigation or governance matter
  given prominence.
- Close with one line on what changed versus the prior period.

Rules:
- Use only what the document states. Never infer, estimate or fill gaps.
- Quote figures with their units and currency exactly as reported.
- If the document does not cover something, leave it out rather than noting its
  absence.
- No preamble, no closing commentary, no investment recommendation.
- Plain text. No markdown headers."""


class SummaryFailed(RuntimeError):
    """The model did not return a usable summary."""


class CredentialsMissing(RuntimeError):
    """No Anthropic credentials are available to this process."""


def build_client(api_key=None):
    """An Anthropic client.

    With no api_key the SDK resolves credentials itself, from
    ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN or an `ant auth login` profile.

    An unauthenticated client constructs without complaint and only fails on
    the first request, several minutes into a run, as a TypeError from inside
    the SDK. Failing here instead keeps that cost off the table.
    """
    try:
        client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        client._validate_headers({}, {})
    except TypeError as exc:
        raise CredentialsMissing(
            "no Anthropic credentials found. Set ANTHROPIC_API_KEY, for example\n"
            '  PowerShell:  $env:ANTHROPIC_API_KEY = "sk-ant-..."\n'
            "  bash:        export ANTHROPIC_API_KEY=sk-ant-...\n"
            "or sign in once with 'ant auth login', which stores a profile the SDK reads."
        ) from exc
    except AttributeError:
        # A future SDK may drop the private helper; the client is still usable.
        pass
    return client


def _prompt(text, report_type, company, title, filed_on):
    label = DOCUMENT_LABELS.get(report_type, "filing")
    header = f"Company: {company}\nDocument: {title}\nType: {label}"
    if filed_on:
        header += f"\nFiled: {filed_on}"
    return f"{header}\n\n---\n\n{text}"


def count_tokens(client, text, report_type, company, title, filed_on="", model=MODEL):
    """Input tokens this document would cost, for a pre-flight estimate.

    Uses the API's own counter rather than a local approximation, because the
    whole point of the estimate is to be right about the bill.
    """
    counted = client.messages.count_tokens(
        model=model,
        system=SYSTEM,
        messages=[{"role": "user", "content": _prompt(text, report_type, company, title, filed_on)}],
    )
    return counted.input_tokens


def summarise(
    client,
    text,
    report_type,
    company,
    title,
    filed_on="",
    model=MODEL,
    effort=DEFAULT_EFFORT,
):
    """A short summary of one filing.

    Raises SummaryFailed when the model declines the request or returns no
    text, so a caller never stores an empty summary as though it succeeded.
    """
    try:
        with client.messages.stream(
            model=model,
            max_tokens=MAX_SUMMARY_TOKENS,
            system=SYSTEM,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            messages=[
                {
                    "role": "user",
                    "content": _prompt(text, report_type, company, title, filed_on),
                }
            ],
        ) as stream:
            message = stream.get_final_message()
    except anthropic.APIStatusError as exc:
        raise SummaryFailed(f"Claude API returned {exc.status_code}: {exc}") from exc
    except anthropic.APIConnectionError as exc:
        raise SummaryFailed(f"could not reach the Claude API: {exc}") from exc

    # Always check stop_reason before reading content: a refusal is an HTTP 200.
    if message.stop_reason == "refusal":
        detail = getattr(message, "stop_details", None)
        category = getattr(detail, "category", None) or "unspecified"
        raise SummaryFailed(f"the model declined this document ({category})")

    summary = "".join(
        block.text for block in message.content if block.type == "text"
    ).strip()
    if not summary:
        raise SummaryFailed(f"the model returned no text (stop_reason: {message.stop_reason})")

    return {
        "summary": summary,
        "model": model,
        "input_tokens": message.usage.input_tokens,
        "output_tokens": message.usage.output_tokens,
    }
