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
    python fetch_feeds.py                # writes articles.json next to this file
    python fetch_feeds.py --out /path/to/articles.json

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

def gnews(query: str) -> str:
    return ("https://news.google.com/rss/search?q="
            + quote_plus(query)
            + "&hl=en-US&gl=US&ceid=US:en")

FEEDS = [
    # (source_label, url)
    ("Google News", gnews("automotive distributor Middle East Europe")),
    ("Google News", gnews("car sales volume Europe GCC")),
    ("Google News", gnews("EV tariff regulation automotive")),
    ("Google News", gnews("used car rental fleet dealer partnership")),
    ("Google News", gnews("automaker earnings EV strategy")),
    # EIN News — Automotive Industry Today (public RSS):
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


# ---------------------------------------------------------------------------
# 3. FETCH + BUILD
# ---------------------------------------------------------------------------
def build(max_per_feed=25):
    seen = set()
    articles = []

    for source_label, url in FEEDS:
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
                date = dt.date(parsed.tm_year, parsed.tm_mon, parsed.tm_mday).isoformat()
            else:
                date = dt.date.today().isoformat()

            blob = f"{title}. {summary}"
            chain = classify(CHAIN_RULES, blob)
            regions = regions_for(blob)
            imp = implication(blob)

            # Country hint: if exactly one region matched, use it; otherwise
            # label the card "Global". Refine to real countries manually.
            country = regions[0] if len(regions) == 1 else "Global"

            articles.append({
                "id": key[:10],
                "chain": chain,
                "type": "news",
                "regions": regions,
                "country": country,         # refine manually for country granularity
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
    return articles


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="articles.json")
    ap.add_argument("--max-per-feed", type=int, default=25)
    args = ap.parse_args()

    articles = build(max_per_feed=args.max_per_feed)
    payload = {
        "generated": dt.datetime.utcnow().isoformat() + "Z",
        "count": len(articles),
        "articles": articles,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(articles)} articles to {args.out}")
    print("NOTE: review chain/region/implication and rewrite each 'implication' "
          "field before publishing — the auto-classifier is a first pass only.")


if __name__ == "__main__":
    main()
