"""Tests for company/entity name normalization (pure)."""

from analytics.entities import normalize


def test_alias_maps_to_canonical():
    assert normalize("google") == "Alphabet (Google)"
    assert normalize("DeepMind") == "Alphabet (Google)"
    assert normalize("waymo") == "Alphabet (Google)"


def test_case_insensitive():
    assert normalize("NVIDIA") == "Nvidia"
    assert normalize("nvda") == "Nvidia"


def test_whitespace_trimmed_on_match():
    assert normalize("  tsmc  ") == "TSMC"


def test_unknown_passthrough_trimmed():
    assert normalize("  SomeStartup  ") == "SomeStartup"


def test_empty_returns_empty():
    assert normalize("") == ""


def test_normalize_strips_legal_suffixes():
    # Legal designator stripped, then alias-resolved to the canonical.
    assert normalize("Alphabet Inc.") == "Alphabet (Google)"
    assert normalize("Block Inc") == "Block"
    assert normalize("Toyota Motor Corp") == "Toyota"          # strip Corp → alias 'toyota motor'
    assert normalize("Micron Technology Inc.") == "Micron"      # strip Inc → alias 'micron technology'
    assert normalize("Cisco Systems Inc") == "Cisco"           # strip Inc → alias 'cisco systems'
    # Untracked names: suffix still stripped (better cross-feed dedup), idempotent.
    assert normalize("Acme Robotics Inc.") == "Acme Robotics"
    assert normalize("Acme Robotics") == "Acme Robotics"
    # Descriptive words are NOT stripped — they're part of brand names.
    assert normalize("Constellation Energy") == "Constellation Energy"
    assert normalize("General Dynamics") == "General Dynamics"


def test_normalize_does_not_overstrip():
    # 'Group' is part of brand names, not a stripped legal form.
    assert normalize("SoftBank Group") == "SoftBank Group"
    assert normalize("Tata Group") == "Tata Group"
    # 'KGaA' separates Merck KGaA (Germany) from the US 'Merck & Co' — must NOT merge.
    assert normalize("Merck KGaA") == "Merck KGaA"
    assert normalize("Merck & Co") == "Merck"
    # Stripping one suffix at a time stops at an alias-bearing intermediate.
    assert normalize("Nu Holdings Ltd") == "Nubank"        # 'Nu Holdings' wins before 'Ltd'+'Holdings'
    assert normalize("CrowdStrike Holdings Inc.") == "CrowdStrike"


def test_co_mentions_excludes_self_and_normalizes():
    from analytics.entity_tracker import co_mentions
    from analytics.weights import article_weight
    nw = article_weight({})  # neutral weight for rows with no impact/source
    stories = [
        {"companies": ["Nvidia", "TSMC", "tsmc"]},
        {"companies": ["Nvidia", "google", "DeepMind"]},  # both -> Alphabet (Google)
    ]
    co = dict(co_mentions(stories, "Nvidia"))
    assert "Nvidia" not in co
    assert co["TSMC"] == round(2 * nw)              # 2 weighted mentions, rounded
    assert co["Alphabet (Google)"] == round(2 * nw)


def test_entity_read_cross_domain_and_tone():
    from analytics.entity_tracker import entity_read
    prof = {"feeds_count": 3, "total": 9, "sentiment": {"positive": 7, "negative": 1},
            "by_feed": {"Chips": 5, "AI & Energy": 3, "Disruptive Tech": 1}}
    txt = entity_read("Nvidia", prof)
    assert "cross-domain" in txt and "3 feeds" in txt
    assert "positive" in txt and "Most active in **Chips**" in txt


def test_entity_read_single_feed():
    from analytics.entity_tracker import entity_read
    prof = {"feeds_count": 1, "total": 2, "sentiment": {"negative": 2}, "by_feed": {"EV": 2}}
    txt = entity_read("Rivian", prof)
    assert "concentrated in **EV**" in txt and "negative" in txt


def test_co_occurrence_matrix_symmetric_and_domain_coloured():
    from analytics.entity_tracker import co_occurrence_matrix
    from analytics.weights import article_weight
    nw = article_weight({})  # neutral weight for rows with no impact/source
    rows = [
        {"_feed_label": "Chips", "companies": ["Nvidia", "TSMC"]},
        {"_feed_label": "AI & Energy", "companies": ["Nvidia", "TSMC"]},
        {"_feed_label": "AI & Energy", "companies": ["Nvidia", "OpenAI"]},
        {"_feed_label": "EV", "companies": ["Tesla"]},  # singleton → no co-occurrence
    ]
    m = co_occurrence_matrix(rows, top=10)
    labels, matrix, domains = m["labels"], m["matrix"], m["domains"]
    assert "Tesla" not in labels                      # no co-mention partner
    i, j = labels.index("Nvidia"), labels.index("TSMC")
    # Edges are significance/source-weighted then rounded; symmetry preserved.
    assert matrix[i][j] == round(2 * nw) and matrix[j][i] == round(2 * nw)
    assert matrix[labels.index("Nvidia")][labels.index("OpenAI")] == round(1 * nw)
    # Coloring is raw presence: Nvidia 2x AI & Energy vs 1x Chips → dominant AI & Energy
    assert domains[labels.index("Nvidia")] == "AI & Energy"


def test_co_occurrence_empty_when_no_pairs():
    from analytics.entity_tracker import co_occurrence_matrix
    assert co_occurrence_matrix([{"companies": ["Solo"]}])["labels"] == []


def test_chord_html_embeds_data_and_d3():
    import json
    from analytics.entity_tracker import chord_html
    data = {"labels": ["Nvidia", "TSMC", "OpenAI"], "domains": ["AI & Energy", "Chips", "AI & Energy"],
            "matrix": [[0, 2, 1], [2, 0, 0], [1, 0, 0]]}
    colors = {"AI & Energy": "#4e79a7", "Chips": "#59a14f"}
    h = chord_html(data, colors)
    assert "__PAYLOAD__" not in h                 # placeholder fully substituted
    assert "cdn.jsdelivr.net/npm/d3@7" in h        # D3 loaded
    assert "d3.chord(" in h and "d3.ribbon(" in h  # chord layout present
    assert '"Nvidia"' in h and '[[0, 2, 1]' in h.replace(" ", "") or "Nvidia" in h
    # the injected JSON round-trips
    import re
    payload = re.search(r"const DATA = (\{.*?\});", h, re.DOTALL).group(1)
    parsed = json.loads(payload)
    assert parsed["matrix"] == data["matrix"] and parsed["labels"] == data["labels"]
