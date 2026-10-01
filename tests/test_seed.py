"""Tests for the pure gold-seed helpers (backend/eval/seed.py)."""

from eval.seed import build_seed_row, dedupe_by_url, stratified_sample


def test_stratified_sample_balances_across_buckets():
    # 10 'a' and 10 'b'; asking for 6 should draw ~3 from each, not 6 'a'.
    items = [("a", i) for i in range(10)] + [("b", i) for i in range(10)]
    out = stratified_sample(items, 6, key_fn=lambda t: t[0])
    a = sum(1 for k, _ in out if k == "a")
    b = sum(1 for k, _ in out if k == "b")
    assert len(out) == 6 and a == 3 and b == 3


def test_stratified_sample_drains_when_n_exceeds_supply():
    items = [("a", 1), ("a", 2), ("b", 1)]
    out = stratified_sample(items, 99, key_fn=lambda t: t[0])
    assert len(out) == 3 and set(out) == set(items)


def test_stratified_sample_deterministic_order_within_bucket():
    items = [("a", 1), ("a", 2), ("a", 3), ("b", 9)]
    out = stratified_sample(items, 4, key_fn=lambda t: t[0])
    # round-robin: a1, b9, a2, a3 — within 'a' the input order is preserved
    a_vals = [v for k, v in out if k == "a"]
    assert a_vals == [1, 2, 3]


def test_stratified_sample_zero_or_negative_n():
    assert stratified_sample([("a", 1)], 0, key_fn=lambda t: t[0]) == []
    assert stratified_sample([("a", 1)], -5, key_fn=lambda t: t[0]) == []


def test_stratified_sample_empty():
    assert stratified_sample([], 5, key_fn=lambda t: t[0]) == []


def test_dedupe_by_url_keeps_first_across_feeds():
    # Same article cross-posted to two feeds → one entry, first feed wins.
    items = [
        ("disruption", {"url": "https://x.com/a", "maturity_stage": "growth"}),
        ("ev", {"url": "https://x.com/b", "maturity_stage": "emerging"}),
        ("ai-energy", {"url": "https://x.com/a", "maturity_stage": "growth"}),  # dup of first
    ]
    out = dedupe_by_url(items, url_fn=lambda fr: fr[1].get("url"))
    assert [fr[1]["url"] for fr in out] == ["https://x.com/a", "https://x.com/b"]
    assert out[0][0] == "disruption"   # first-seen feed retained


def test_dedupe_by_url_empty():
    assert dedupe_by_url([], url_fn=lambda fr: fr) == []


def test_build_seed_row_prefills_guess_and_context():
    row = {
        "url": "https://x.com/a", "title": "T", "summary": "S",
        "maturity_stage": "growth", "adoption_stage": "early-adopters",
        "business_impact": "material", "scope": "deal",
    }
    seed = build_seed_row(row, "ev")
    assert seed["url"] == "https://x.com/a" and seed["feed"] == "ev"
    # the four gold fields are pre-filled with the lens's guess (to be verified)
    assert seed["maturity_stage"] == "growth" and seed["scope"] == "deal"
    # article text travels as underscore context (ignored by load_gold)
    assert seed["_title"] == "T" and seed["_summary"] == "S"
    assert seed["notes"] == ""


def test_build_seed_row_no_prefill_blanks_fields_and_keeps_guess():
    row = {"url": "https://x.com/a", "title": "T", "summary": "S",
           "maturity_stage": "growth", "adoption_stage": "early-adopters",
           "business_impact": "material", "scope": "deal"}
    seed = build_seed_row(row, "ev", prefill=False)
    assert seed["maturity_stage"] is None and seed["scope"] is None
    assert seed["_guess"]["maturity_stage"] == "growth"      # guess kept for reference
    # loads as a gold label with NOTHING scored yet (forces a real labelling decision)
    from eval.gold import label_from_dict
    assert label_from_dict(seed).labelled_fields == {}


def test_seed_rows_roundtrip_through_load_gold_on_disk(tmp_path):
    # Prove the ON-DISK JSONL round-trip: serialize exactly as gold_seed.py does,
    # then load_gold it back (underscore keys ignored, unicode + n/a preserved).
    import json
    from eval.gold import load_gold
    rows = [
        build_seed_row({"url": "https://x.com/a", "title": "Café ™", "summary": "S",
                        "maturity_stage": "growth", "adoption_stage": "n/a",
                        "business_impact": "contextual", "scope": "sector"}, "ev"),
        build_seed_row({"url": "https://x.com/b", "title": "T2", "summary": "S2",
                        "maturity_stage": "emerging", "adoption_stage": "innovators",
                        "business_impact": "none", "scope": "single-company"}, "chips"),
    ]
    f = tmp_path / "seed.jsonl"
    f.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    labs = load_gold(f)
    assert [l.url for l in labs] == ["https://x.com/a", "https://x.com/b"]
    assert labs[0].maturity_stage == "growth" and labs[0].adoption_stage == "n/a"
    assert labs[0].feed == "ev" and labs[1].feed == "chips"
