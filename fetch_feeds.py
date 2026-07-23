#!/usr/bin/env python3
"""
fetch_feeds.py — Mobility Intelligence feed builder (Option B)
===============================================================

Pulls automotive news from public RSS feeds, classifies each item into the
Mobility Intelligence schema (value chain, region, implication strength),
de-duplicates, and writes `articles.json` for the front-end to load.

WHICH SOURCES THIS USES, AND WHY
--------------------------------
Of the three sources you named, two expose usable RSS feeds and one does not:

  * Google News  -> YES. Google News has no official API, but it publishes RSS
                    feeds per topic/search. This script uses topic + query RSS.
                    Google News mostly links OUT to publishers; we keep the link
                    to the original and attribute the publisher.
  * EIN News     -> YES. "Automotive Industry Today" publishes an RSS feed.
  * NewsNow      -> NO.  NewsNow's terms prohibit scraping/redistribution and it
                    offers no reuse-friendly feed. It is intentionally NOT fetched.
                    Use it for manual monitoring only.

You can add more publisher/official feeds (Reuters, ACEA, OEM newsrooms,
regulators) in FEEDS below — original sources are cleaner to reuse than
aggregators and are preferred for anything client-facing.

USAGE
-----
    pip install feedparser
    python fetch_feeds.py                # news on/after 2026-01-01 -> articles.json
    python fetch_feeds.py --since 2026-06-01   # tighter window
    python fetch_feeds.py --since ""           # no date floor (everything)
    python fetch_feeds.py --out /path/to/articles.json

By default only news published on or after 1 January 2026 is included. This is
enforced two ways: Google News queries carry an `after:` operator, and build()
applies a hard date floor that also covers feeds (like EIN) that ignore it.
Undated items are dropped whenever a floor is set.

Run it on a schedule (cron / GitHub Action / cloud scheduler) each fortnight,
then host articles.json next to the HTML. See the companion note for how to
point the front-end at it.

CLASSIFICATION IS HEURISTIC
---------------------------
Chain / region / implication are assigned by keyword rules below. They are a
first pass, not editorial judgement — review and correct before publishing,
especially the implication (strong/less) flag, which drives the "so-what".
"""

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from urllib.parse import quote_plus

try:
    import feedparser
except ImportError:
    sys.exit("Missing dependency. Run:  pip install feedparser")


# ---------------------------------------------------------------------------
# 1. FEEDS  — add or remove sources here.
# ---------------------------------------------------------------------------
# Google News RSS patterns:
#   Topic:  https://news.google.com/rss/headlines/section/topic/BUSINESS
#   Search: https://news.google.com/rss/search?q=YOUR+QUERY&hl=en&gl=US&ceid=US:en
# We use targeted searches so results map cleanly onto the value chain.
#
# Google News supports search operators inside q=, including `after:YYYY-MM-DD`
# (and `before:`), so we can ask the feed itself to return only recent items.
# A hard date floor is ALSO applied in build() to catch feeds that ignore it.

# Only include news published on/after this date. Overridable with --since.
SINCE_DEFAULT = "2026-01-01"


def gnews(query: str, since: str = SINCE_DEFAULT) -> str:
    q = f"{query} after:{since}" if since else query
    return ("https://news.google.com/rss/search?q="
            + quote_plus(q)
            + "&hl=en-US&gl=US&ceid=US:en")


def build_feeds(since: str = SINCE_DEFAULT):
    """Feed list, built with the date floor baked into Google News queries."""
    return [
        # (source_label, url)
        ("Google News", gnews("automotive distributor Middle East Europe", since)),
        ("Google News", gnews("car sales volume Europe GCC", since)),
        ("Google News", gnews("EV tariff regulation automotive", since)),
        ("Google News", gnews("used car rental fleet dealer partnership", since)),
        ("Google News", gnews("automaker earnings EV strategy", since)),
        # EIN News — Automotive Industry Today (public RSS). The `after:` operator
        # does not apply here; the date floor in build() handles it instead.
        ("EIN Automotive Industry Today",
         "https://automotive.einnews.com/rss/2Xr4kU8fJ9-tV3bp"),  # replace with the exact feed URL from the EIN page
        # --- Preferred: add original-source / official feeds below ---
        # ("Reuters Autos", "https://www.reutersagency.com/feed/?best-topics=automotive&post_type=best"),
        # ("ACEA", "https://www.acea.auto/rss/news.xml"),
    ]


# ---------------------------------------------------------------------------
# 2. CLASSIFIERS
# ---------------------------------------------------------------------------
CHAIN_RULES = [
    # order matters: first match wins
    ("regulation",  r"\b(tariff|regulation|rule|mandate|emission|homologation|"
                    r"import duty|ban|policy|law|type-approval|CO2|standard)\b"),
    ("aftermarket", r"\b(used car|pre-owned|rental|rent a car|hire|leasing|lease|"
                    r"subscription|maintenance|repair|workshop|aftersales|"
                    r"spare part|warranty|fleet)\b"),
    ("distribution",r"\b(dealer|dealership|distributor|distribution|showroom|"
                    r"retail|agency model|sub-dealer|franchise)\b"),
    ("automakers",  r"\b(oem|manufacturer|automaker|carmaker|earnings|profit|"
                    r"revenue|production|model|launch|plant|assembly)\b"),
    ("market",      r".*"),  # default
]

REGION_PATTERNS = {
    "Middle East": r"\b(gcc|uae|dubai|abu dhabi|saudi|ksa|qatar|oman|kuwait|"
                   r"bahrain|egypt|middle east|gulf|levant)\b",
    "Europe":      r"\b(eu|europe|european|germany|france|uk|britain|italy|"
                   r"spain|acea|brussels)\b",
    "Rest of World": r"\b(china|chinese|japan|usa|u\.s\.|america|india|"
                     r"korea|brazil|australia|africa)\b",
}
ALL_REGIONS = ["Middle East", "Europe", "Rest of World"]

# Country detection. Each country maps to the phrases that imply it, plus the
# region it belongs to (used only as a sanity cross-check). Order matters:
# more specific / higher-priority entries first. The first match wins, so a
# headline mentioning both "Saudi" and "China" is tagged by whichever appears
# earliest in this list — tune the order to your priorities.
COUNTRY_PATTERNS = [
    # (display label, regex)
    # Regional bodies first: an article about EU policy that merely mentions
    # "Chinese EVs" should tag as EU, not China.
    ("EU",           r"\b(european union|acea|brussels|european commission|"
                     r"eu\s+\w+\s+(tariff|rule|regulation|mandate|market|deal|law)|"
                     r"eu\s+(tariff|rule|regulation|mandate|market|deal|law))\b"),
    ("UAE",          r"\b(uae|u\.a\.e\.|emirati|dubai|abu dhabi|sharjah)\b"),
    ("Saudi Arabia", r"\b(saudi|k\.?s\.?a\.?|riyadh|jeddah)\b"),
    ("Qatar",        r"\b(qatar|doha)\b"),
    ("Oman",         r"\b(oman|muscat)\b"),
    ("Kuwait",       r"\bkuwait\b"),
    ("Bahrain",      r"\bbahrain\b"),
    ("Egypt",        r"\b(egypt|cairo|egyptian)\b"),
    ("Germany",      r"\b(germany|german|berlin|munich)\b"),
    ("France",       r"\b(france|french|paris)\b"),
    ("UK",           r"\b(uk|u\.k\.|britain|british|england|london)\b"),
    ("Italy",        r"\b(italy|italian|rome|milan)\b"),
    ("Spain",        r"\b(spain|spanish|madrid)\b"),
    ("China",        r"\b(china|chinese|beijing|shanghai|shenzhen)\b"),
    ("Japan",        r"\b(japan|japanese|tokyo)\b"),
    ("USA",          r"\b(usa|u\.s\.a?\.?|united states|american|washington)\b"),
    ("India",        r"\b(india|indian|delhi|mumbai)\b"),
    ("South Korea",  r"\b(south korea|korean|seoul)\b"),
    ("Brazil",       r"\b(brazil|brazilian)\b"),
    # Generic "EU"/"Europe" as a last resort if nothing more specific matched
    ("EU",           r"\b(eu|europe|european)\b"),
]


def country_for(text):
    """Return a specific country if the text names one, else None.

    None means 'no country found' — the caller then falls back to a region
    label, so the country tag never simply echoes the region tag."""
    for label, pattern in COUNTRY_PATTERNS:
        if re.search(pattern, text, re.I):
            return label
    return None


def regions_for(text):
    """Return every region an article is relevant to.

    A story can match more than one (e.g. an EU-China tariff touches both
    Europe and Rest of World). If nothing matches, treat it as globally
    relevant -> all three, so it surfaces under every region filter."""
    hits = [r for r, pat in REGION_PATTERNS.items() if re.search(pat, text, re.I)]
    return hits or list(ALL_REGIONS)

# Strong = a concrete opportunity/risk to a distributor (enabling/limiting
# regulation, supply shocks, channel shifts, partnership openings).
# Less   = informational (financial results, rankings, general market data).
STRONG_SIGNALS = re.compile(
    r"\b(tariff|regulation|mandate|ban|incentive|subsidy|shortage|disruption|"
    r"supply chain|partnership|agency model|direct sales|acquires|acquisition|"
    r"enters|expansion|launch|recall|price war|shipping|logistics cost)\b",
    re.I,
)
LESS_SIGNALS = re.compile(
    r"\b(earnings|profit|revenue|results|quarter|ranking|market share|"
    r"forecast|survey|report|study|index)\b",
    re.I,
)


def classify(field_rules, text):
    text = text.lower()
    for label, pattern in field_rules:
        if re.search(pattern, text, re.I):
            return label
    return field_rules[-1][0]


def implication(text):
    strong = len(STRONG_SIGNALS.findall(text))
    less = len(LESS_SIGNALS.findall(text))
    # Bias toward "strong" only when a strong signal clearly leads.
    if strong and strong >= less:
        return "strong"
    if less:
        return "less"
    return "less"  # default conservative


def publisher_from_google_title(title):
    # Google News titles are usually "Headline - Publisher"
    if " - " in title:
        head, pub = title.rsplit(" - ", 1)
        return head.strip(), pub.strip()
    return title.strip(), ""


def clean_title(title):
    """Remove residual publisher tags some feeds append to headlines.

    publisher_from_google_title() handles the standard ' - Publisher' form,
    but some sources (e.g. Eurasia Review) append the publisher after a
    non-breaking space or a double space, which slips through. This strips:
      * a trailing '  Publisher' or ' \xa0Publisher' (2+ spaces / nbsp), and
      * a trailing ' - / – / — / | Publisher' that survived earlier splitting.
    The publisher name is assumed to be a short (<=40 char) tail."""
    t = title.replace("\u00a0", " ")
    # " - Publisher" / " | Publisher" style
    t = re.sub(r"\s+[-–—|]\s+[^-–—|]{1,40}$", "", t)
    # "  Publisher" (two or more spaces before a capitalised short tail)
    t = re.sub(r"\s{2,}[A-Z][\w.& ]{1,40}$", "", t)
    return t.strip()


# ---------------------------------------------------------------------------
# 3. FETCH + BUILD
# ---------------------------------------------------------------------------
def build(since=SINCE_DEFAULT, max_per_feed=25):
    seen = set()
    articles = []
    skipped_old = 0
    since_date = dt.date.fromisoformat(since) if since else None

    for source_label, url in build_feeds(since):
        feed = feedparser.parse(url)
        for entry in feed.entries[:max_per_feed]:
            raw_title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            summary = re.sub(r"<[^>]+>", "", entry.get("summary", "")).strip()

            title, gpub = publisher_from_google_title(raw_title)
            author = gpub or source_label

            # dedupe on normalised title
            key = hashlib.md5(re.sub(r"\W+", "", title.lower()).encode()).hexdigest()
            if key in seen or not title or not link:
                continue
            seen.add(key)

            # date
            parsed = entry.get("published_parsed") or entry.get("updated_parsed")
            if parsed:
                item_date = dt.date(parsed.tm_year, parsed.tm_mon, parsed.tm_mday)
            else:
                item_date = None

            # Hard date floor: keep only items on/after `since`. Items with no
            # parseable date are dropped when a floor is set, so nothing older
            # (or of unknown age) slips through.
            if since_date is not None:
                if item_date is None or item_date < since_date:
                    skipped_old += 1
                    continue

            date = (item_date or dt.date.today()).isoformat()

            title = clean_title(title)
            blob = f"{title}. {summary}"
            chain = classify(CHAIN_RULES, blob)
            regions = regions_for(blob)
            imp = implication(blob)

            # Country tag: detect a real country from the text. Only if none is
            # found do we fall back to a region label, so the country tag never
            # simply repeats the region tag. If the region is multi (global) and
            # no country matched, label it "Global".
            country = country_for(blob)
            if not country:
                country = regions[0] if len(regions) == 1 else "Global"

            articles.append({
                "id": key[:10],
                "chain": chain,
                "type": "news",
                "regions": regions,
                "country": country,
                "date": date,
                "title": title,
                "summary": summary[:400] or title,
                "implication": ("REVIEW: auto-classified as "
                                f"{'strong' if imp=='strong' else 'less'} implication "
                                "— replace with the so-what for a ME/Europe distributor."),
                "author": author,
                "impact": imp,
                "url": link,
                "source_feed": source_label,
            })

    # newest first
    articles.sort(key=lambda a: a["date"], reverse=True)
    return articles, skipped_old


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="articles.json")
    ap.add_argument("--max-per-feed", type=int, default=25)
    ap.add_argument("--since", default=SINCE_DEFAULT,
                    help="Only include news on/after this ISO date "
                         f"(YYYY-MM-DD). Default {SINCE_DEFAULT}. "
                         "Pass an empty string to disable the floor.")
    args = ap.parse_args()

    since = args.since or None
    articles, skipped_old = build(since=since, max_per_feed=args.max_per_feed)
    payload = {
        "generated": dt.datetime.utcnow().isoformat() + "Z",
        "since": since,
        "count": len(articles),
        "articles": articles,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    floor_msg = f"on/after {since}" if since else "with no date floor"
    print(f"Wrote {len(articles)} articles ({floor_msg}) to {args.out}")
    if skipped_old:
        print(f"Skipped {skipped_old} item(s) older than {since} or undated.")
    print("NOTE: review chain/region/implication and rewrite each 'implication' "
          "field before publishing — the auto-classifier is a first pass only.")


if __name__ == "__main__":
    main()
