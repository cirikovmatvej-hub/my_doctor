"""
The in-app Sources screen is built from the hand-written citation strings in
data/ — which mix several references per string, notes about the rule, and a
few explanations with no link. These pin down how those become a clean list.
"""
from fastapi.testclient import TestClient

from api.main import app
from api.routers.sources import _best_titles, _references
from data.bad_safety import get_bad_sources
from data.general_supplements import GENERAL_SUPPLEMENTS, get_general_sources
from data.resources import BAD_DETAILS

client = TestClient(app)


def test_plain_citation():
    assert _references("AAFP — Glucosamine: https://www.aafp.org/x.html") == [
        ("https://www.aafp.org/x.html", "AAFP — Glucosamine", False)
    ]


def test_several_references_in_one_string():
    raw = "NIH ODS Vitamin D: https://a.example/d ; PMC6693398 (Magnesium and vitamin D): https://b.example/p"
    assert [(u, t) for u, t, _ in _references(raw)] == [
        ("https://a.example/d", "NIH ODS Vitamin D"),
        ("https://b.example/p", "PMC6693398 (Magnesium and vitamin D)"),
    ]


def test_note_about_the_rule_is_not_part_of_the_title():
    raw = "NIH ODS — Vitamin D (Consumer Fact Sheet): тиазидные диуретики повышают кальций. https://a.example/c"
    assert _references(raw)[0][1] == "NIH ODS — Vitamin D (Consumer Fact Sheet)"


def test_a_colon_inside_a_real_title_is_kept():
    raw = "NIH NCCIH — Melatonin: What You Need To Know: https://a.example/m"
    assert _references(raw)[0][1] == "NIH NCCIH — Melatonin: What You Need To Know"


def test_explanation_without_a_link_is_not_a_reference():
    assert _references("Задокументированный механизм: магний блокирует вход кальция в нервные окончания.") == []


def test_see_pointer_loses_to_a_proper_name_for_the_same_page():
    pointer = "Механизм: при саркоидозе вырабатывается избыток витамина D — см. NIH ODS Vitamin D fact sheet: https://a.example/d"
    proper = "NIH Office of Dietary Supplements — Vitamin D (Health Professional Fact Sheet): https://a.example/d"
    assert _best_titles([pointer, proper]) == {
        "https://a.example/d": "NIH Office of Dietary Supplements — Vitamin D (Health Professional Fact Sheet)"
    }
    # …but is used when it is the only name there is, rather than dropping the link
    assert _best_titles([pointer]) == {"https://a.example/d": "NIH ODS Vitamin D fact sheet"}


def test_same_page_is_listed_once_under_its_plainest_name():
    raws = [
        "NIH ODS — Vitamin D (Health Professional Fact Sheet), раздел Safety/Toxicity: https://a.example/d",
        "NIH ODS — Vitamin D (Health Professional Fact Sheet): https://a.example/d",
    ]
    assert _best_titles(raws) == {"https://a.example/d": "NIH ODS — Vitamin D (Health Professional Fact Sheet)"}


def test_the_vitamin_k_string_yields_both_of_its_references():
    raw = next(s for k in BAD_DETAILS for s in get_bad_sources(k) if "PMC11313760" in s)
    assert dict((u, t) for u, t, _ in _references(raw)) == {
        "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11313760/": (
            "PMC11313760 — The Importance of Vitamin K and the Combination of Vitamins K and D "
            "for Calcium Metabolism and Bone Health: A Review"
        ),
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC11198368/": "AVADEC trial (JACC: Advances, PMC11198368)",
    }


def test_endpoint_is_public_and_lists_every_cited_page():
    resp = client.get("/sources")   # no Authorization header
    assert resp.status_code == 200
    body = resp.json()

    listed = [s["url"] for group in body["catalog"] + body["other"] for s in group["sources"]]
    assert all(url.startswith("https://") for url in listed)
    assert all(s["title"] and not s["title"].startswith("Механизм") for g in body["catalog"] + body["other"] for s in g["sources"])

    # nothing the data layer cites is missing, and nothing is invented
    cited = set()
    for key in BAD_DETAILS:
        cited |= {u for raw in get_bad_sources(key) for u, _, _ in _references(raw)}
    for key in GENERAL_SUPPLEMENTS:
        cited |= {u for raw in get_general_sources(key) for u, _, _ in _references(raw)}
    assert set(listed) == cited


def test_products_with_identical_references_share_a_group():
    catalog = client.get("/sources").json()["catalog"]
    magnesium = next(g for g in catalog if any("Магний" in n for n in g["names"]))
    assert len(magnesium["names"]) == 2      # the chelate and the B6 citrate
