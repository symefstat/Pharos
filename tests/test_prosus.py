"""Prosus portfolio lens — matcher and region mapping (pure logic)."""

from prosus.matcher import build_alias_index, match_prosus_tags
from prosus.regions import countries_for_region, region_for_country

_COMPANIES = [
    {"slug": "ifood", "aliases": ["iFood"], "status": "active"},
    {"slug": "just-eat-takeaway",
     "aliases": ["Just Eat Takeaway", "Just Eat", "Takeaway.com", "Lieferando"],
     "status": "active"},
    {"slug": "rapido", "aliases": ["Rapido"], "status": "active"},
    {"slug": "oda", "aliases": [], "status": "active"},          # manual-only
    {"slug": "avito", "aliases": ["Avito"], "status": "exited"},  # exited
]


def _index():
    return build_alias_index(_COMPANIES)


class TestBuildAliasIndex:
    def test_skips_empty_aliases_and_exited(self):
        slugs = {slug for slug, _ in _index()}
        assert "oda" not in slugs and "avito" not in slugs
        assert {"ifood", "just-eat-takeaway", "rapido"} <= slugs


class TestMatchProsusTags:
    def test_case_insensitive_title_match(self):
        assert match_prosus_tags(_index(), "IFOOD expands in Brazil", None) == ["ifood"]

    def test_word_boundary_no_substring_match(self):
        # 'rapidly' must not match 'Rapido'
        assert match_prosus_tags(_index(), "AI adoption grows rapidly", None) == []

    def test_dotted_alias_matches(self):
        got = match_prosus_tags(_index(), None, "Takeaway.com posts record orders")
        assert got == ["just-eat-takeaway"]

    def test_matches_agent_extracted_companies_field(self):
        got = match_prosus_tags(_index(), "Food delivery roundup", "Weekly recap",
                                companies=["Just Eat", "DoorDash"])
        assert got == ["just-eat-takeaway"]

    def test_multiple_matches_sorted_and_deduped(self):
        got = match_prosus_tags(_index(), "iFood and Rapido in talks",
                                "iFood again", None)
        assert got == ["ifood", "rapido"]

    def test_empty_inputs(self):
        assert match_prosus_tags(_index(), None, None, None) == []


class TestRegions:
    def test_core_lenses(self):
        assert region_for_country("BR") == "latam"
        assert region_for_country("IN") == "india"
        assert region_for_country("NL") == "europe"

    def test_global_and_unknown(self):
        assert region_for_country("GLOBAL") == "global"
        assert region_for_country("global") == "global"
        assert region_for_country("XX") == "other"
        assert region_for_country(None) == "other"

    def test_every_country_maps_to_exactly_one_region(self):
        seen: dict[str, str] = {}
        from prosus.regions import REGION_COUNTRIES
        for region, ccs in REGION_COUNTRIES.items():
            for cc in ccs:
                assert cc not in seen, f"{cc} in both {seen.get(cc)} and {region}"
                seen[cc] = region

    def test_countries_for_region_roundtrip(self):
        assert "IN" in countries_for_region("india")
        assert countries_for_region("nope") == []
