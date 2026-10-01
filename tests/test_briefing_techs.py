"""Signal → dossier chip matching (pure)."""

from backend.app.briefing import match_signal_techs
from technologies import TECHNOLOGIES


def test_signals_gain_tech_chips_capped_at_two():
    signals = [
        {"title": "Foundry pricing power flips as advanced logic capacity tightens",
         "implication": "TSMC raising 3nm wafer prices"},
        {"title": "A policy story about tariffs", "implication": "no technology here"},
    ]
    out = match_signal_techs(signals, TECHNOLOGIES)
    assert len(out) == 2
    keys = [t["key"] for t in out[0]["techs"]]
    assert len(keys) <= 2
    assert out[1]["techs"] == [] or len(out[1]["techs"]) <= 2
    # labels resolve from the registry
    for t in out[0]["techs"]:
        assert t["label"]
