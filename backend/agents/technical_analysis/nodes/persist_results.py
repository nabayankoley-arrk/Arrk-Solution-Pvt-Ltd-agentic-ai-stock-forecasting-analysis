"""persist_results — terminal node.

Writes the completed analysis to "Technical".technical_analysis_results so
a later request for the same ticker/day can be served from that cached row
instead of recomputing indicators (see fetch_price_history.py and the
table's own comment). Only reached after build_final_response on the
success path (see graph.py) -- build_error_response short-circuits before
as_of_date/classifications exist, so it skips this node entirely.

Reads `final_output` for the fields build_final_response already merged
(ticker, as_of_date, technical_signal, confidence, support_resistance,
candlestick_pattern, pattern_direction, trade_setup) plus the raw `trend`/
`momentum`/`volatility` state and the two guard results (prior_trend_ok,
volume_ok) for technical_summary, since those aren't carried into
final_output.
"""

from db.upsert import save_technical_analysis_results


def persist_results(state):
    final_output = state.get("final_output") or {}
    trend = state.get("trend") or {}
    momentum = state.get("momentum") or {}
    volatility = state.get("volatility") or {}
    support_resistance = final_output.get("support_resistance") or {}
    technical_signal = final_output.get("technical_signal") or {}
    candlestick_pattern = final_output.get("candlestick_pattern") or {}
    trade_setup = final_output.get("trade_setup") or {}
    prior_trend_ok = state.get("prior_trend_ok") or {}
    volume_ok = state.get("volume_ok") or {}

    record = {
        "ticker": final_output.get("ticker"),
        "analysis_date": final_output.get("as_of_date"),
        "trend": trend.get("classification"),
        "momentum": momentum.get("classification"),
        "volatility": volatility.get("classification"),
        "support_level": support_resistance.get("support"),
        "resistance_level": support_resistance.get("resistance"),
        "overall_direction": technical_signal.get("direction"),
        "confidence_score": final_output.get("confidence"),
        "candlestick_pattern": candlestick_pattern.get("name"),
        "pattern_direction": final_output.get("pattern_direction"),
        "volume_confirmed": volume_ok.get("passed"),
        "trend_aligned": prior_trend_ok.get("passed"),
        "entry_price": trade_setup.get("entry_price"),
        "stop_loss": trade_setup.get("stop_loss"),
        "target_price": trade_setup.get("target"),
        "risk_reward_ratio": trade_setup.get("rrr"),
        "trade_status": trade_setup.get("status"),
        "technical_summary": {
            "trend_detail": trend.get("detail"),
            "momentum_detail": momentum.get("detail"),
            "volatility_detail": volatility.get("detail"),
            "support_resistance_detail": support_resistance.get("detail"),
            "prior_trend_alignment": prior_trend_ok or None,
            "volume_confirmation": volume_ok or None,
            "trade_setup_reason": trade_setup.get("reason"),
        },
    }
    save_technical_analysis_results(record)
    return {}
