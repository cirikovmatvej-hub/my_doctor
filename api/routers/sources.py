"""
The citations behind the app's safety checks, for an in-app "Sources" screen.

They are the same strings the bot quotes when someone asks what it relies on
(data.bad_safety.get_bad_sources / data.general_supplements.get_general_sources)
— real references attached to the contraindication, interaction and synergy
rules. Public and static: nothing here is user data.
"""
import re

from fastapi import APIRouter

from api.schemas import SourceGroupOut, SourceOut, SourcesOut
from data.bad_safety import get_bad_sources
from data.general_supplements import GENERAL_SUPPLEMENTS, get_general_sources
from data.resources import BAD_DETAILS

router = APIRouter(tags=["sources"])

_URL = re.compile(r"https?://[^\s,;)]+")
# A Russian annotation after the title ("…Fact Sheet: тиазидные диуретики …") is
# commentary on the rule, not part of the reference's name. A colon inside a
# real English title ("Melatonin: What You Need To Know") is kept.
_ANNOTATION = re.compile(r":\s+(?=[а-яё])", re.IGNORECASE)

# The one citation string that packs two references into running prose; its
# per-URL text can't be recovered mechanically.
_TITLE_OVERRIDES = {
    "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11313760/": (
        "PMC11313760 — The Importance of Vitamin K and the Combination of Vitamins K and D "
        "for Calcium Metabolism and Bone Health: A Review"
    ),
    "https://pmc.ncbi.nlm.nih.gov/articles/PMC11198368/": "AVADEC trial (JACC: Advances, PMC11198368)",
}


_CROSS_REFERENCE = re.compile(r"\s—?\s*см\.\s+", re.IGNORECASE)


def _references(raw: str) -> list[tuple[str, str, bool]]:
    """(url, title, is_cross_reference) triples in one citation string. The
    strings are hand-written: some hold several references joined by " ; ",
    some carry a note about the rule before the link, and a few have no link at
    all (pure explanation — not a reference, so nothing is returned for them).

    "…объяснение механизма — см. NIH ODS … fact sheet: <url>" is a pointer to a
    page named elsewhere, so its title is flagged as a weak candidate."""
    refs = []
    for segment in re.split(r"\s;\s", raw):
        previous_end = 0
        for match in _URL.finditer(segment):
            url = match.group(0).rstrip(".")
            title = segment[previous_end:match.start()].strip(" :.;,—-")
            weak = False
            if _CROSS_REFERENCE.search(title):
                title = _CROSS_REFERENCE.split(title, maxsplit=1)[1].strip()
                weak = True
            else:
                title = _ANNOTATION.split(title, maxsplit=1)[0].strip()
            title = _TITLE_OVERRIDES.get(url, title)
            if title:
                refs.append((url, title, weak))
            previous_end = match.end()
    return refs


def _best_titles(all_raw: list[str]) -> dict[str, str]:
    """The same page is cited many times with different notes attached; show
    it once, under its plainest (shortest) proper name, falling back to a
    "см. …" pointer only if that is all there is."""
    best: dict[str, tuple[bool, int, str]] = {}
    for raw in all_raw:
        for url, title, weak in _references(raw):
            candidate = (weak, len(title), title)
            if url not in best or candidate < best[url]:
                best[url] = candidate
    return {url: title for url, (_, _, title) in best.items()}


def _grouped(items: list[tuple[str, list[str]]], titles: dict[str, str]) -> list[SourceGroupOut]:
    """Products backed by exactly the same references (e.g. the two magnesium
    products) share one group instead of repeating the list."""
    by_sources: dict[tuple[str, ...], list[str]] = {}
    for name, raws in items:
        urls: list[str] = []
        for raw in raws:
            for url, _, _ in _references(raw):
                if url not in urls:
                    urls.append(url)
        if urls:
            by_sources.setdefault(tuple(urls), []).append(name)
    return [
        SourceGroupOut(names=names, sources=[SourceOut(title=titles[u], url=u) for u in urls])
        for urls, names in by_sources.items()
    ]


@router.get("/sources", response_model=SourcesOut)
async def list_sources() -> SourcesOut:
    catalog = [(d["full_name"], get_bad_sources(key)) for key, d in BAD_DETAILS.items()]
    other = [(d["label"], get_general_sources(key)) for key, d in GENERAL_SUPPLEMENTS.items()]
    titles = _best_titles([raw for _, raws in catalog + other for raw in raws])
    return SourcesOut(catalog=_grouped(catalog, titles), other=_grouped(other, titles))
