# Mobility Intelligence — fortnightly automotive intelligence dashboard

A self-contained web app that surfaces mobility-sector news for an automotive
distributor operating across the Middle East and Europe. It ships pre-loaded
with a real snapshot of current news and can optionally read a live feed.

## Files in this bundle

1. **`mobility-intelligence.html`** — the dashboard. A single, self-contained
   file (no build step, no dependencies) pre-loaded with a real snapshot of
   automotive news pulled 23 Jul 2026, each item mapped into the schema below.
   Works offline. This is **Option A**.
2. **`fetch_feeds.py`** — a feed builder that regenerates `articles.json` from
   public RSS feeds on a schedule. Drop the output next to the HTML and the
   dashboard loads it automatically. This is **Option B**.
3. **`articles.json`** *(you generate this)* — the news feed, produced by
   `fetch_feeds.py` and hosted next to the HTML.
4. **`proposedactions.json`** *(optional; you export/commit this)* — shared
   proposed actions the dashboard reads on load. Produced by the app's
   **Export actions** button.
5. **`README.md`** — this file.

## How the dashboard is organised

**Level 1 — primary tabs (top nav)**
- **Latest News** — items dated within the last 14 days.
- **Older News** — items older than 14 days.
- **Opinions** — commentary from industry thought leaders (kept separate from
  reported news).
- **Saved Articles** — anything you've saved, across news and opinions. A live
  count badge shows on the tab. Saved items persist in the browser on the
  device (localStorage).
- **Pending Action** — every article that has an open proposed action. A live
  count badge shows on the tab. Marking an action done removes it from here.

Each article card links to its original source **through the headline**
(the title itself is the link). There is no separate "Read source" link.

**Level 2 — automotive value chain (secondary bar; Latest/Older only)**
- **Market** — market, macroeconomic and **consumer-trend** developments
  (sales volumes, demand shifts, buyer preferences, logistics costs, macro
  shocks).
- **Automakers** — vehicle and parts manufacturers (products, powertrains,
  financial performance, strategy).
- **Distribution** — distribution players (retail innovation, agency models,
  network, financial performance).
- **Aftermarket** — used cars, hire/rental, and maintenance & repair (service
  players and used-car/rental firms serving or partnering with distributors).
- **Regulation** — tariffs, emissions standards, EV mandates, import rules,
  homologation.

**Level 3 — region filter (news tabs and Opinions)**
- **All / Middle East / Europe / Rest of World.** Regions are **overlapping,
  not exclusive** — an article records every region it's relevant to, so a
  genuinely global story (e.g. an EU–China tariff) surfaces under Middle East,
  Europe *and* Rest of World rather than hiding in a separate bucket. Articles
  relevant to all three show a "Global" label on the card. "All" shows the
  comprehensive list.

(The earlier "implication" filter and the "Why it matters to us" line have been
removed.)

## Proposed actions

Each article card has a **Proposed action** text box with **Save** and **Mark
done** buttons. Saved actions persist in the browser (localStorage) and feed the
**Pending Action** tab. Marking an action done deletes it.

Because a static site (e.g. GitHub Pages) cannot write files from the browser,
sharing actions across people works via export + commit:

1. Enter and save actions in the app.
2. Click **Export actions** (top nav) to download `proposedactions.json`.
3. Commit that file to the repo next to the HTML.
4. On load, the app reads `proposedactions.json` and shows those actions for
   everyone. On conflict, the committed shared file wins over a local entry.

`proposedactions.json` shape:

```json
{
  "generated": "2026-07-23T...Z",
  "count": 2,
  "actions": {
    "<articleId>": "Brief the GCC team on hybrid stock weighting",
    "<articleId>": "Confirm which EU models meet recycled-content thresholds"
  }
}
```

Action text is tied to an article by its `id`. Note that the built-in snapshot
and the live `articles.json` use different ids, so actions attach to whichever
dataset is loaded — keep `articles.json` in place for ids to stay stable.

## Article schema

Each article is an object:

```js
{
  id, chain, type,            // chain: market|automakers|distribution|aftermarket|regulation
                              // type:  news | opinion
  regions,                    // array, e.g. ["Middle East"] or
                              //   ["Middle East","Europe","Rest of World"] (global)
  country,                    // a real country when detected (UAE, Germany, China…),
                              //   otherwise a region label; shown with a flag
  date,                       // ISO date; drives Latest (<=14d) vs Older
  title, summary,             // title is cleaned of trailing publisher tags
  author, url                 // source attribution; url backs the headline link
}
```

`impact` and `implication` fields may still appear in feed output but are no
longer displayed by the front-end. The front-end also accepts a legacy single
`region` string (with `"Global"` expanding to all three regions), so a
partially-updated feed won't break it.

## Option A — use the snapshot as-is

Just open or host `mobility-intelligence.html`. Every card links back to its
original source. To refresh for the next fortnight, re-run a manual pull or
switch to Option B.

## Option B — automated fortnightly feed

    pip install feedparser
    python fetch_feeds.py            # news on/after 2026-01-01 -> articles.json

By default the script only pulls news published **on or after 1 January 2026**.
Override with `--since YYYY-MM-DD` (e.g. `--since 2026-06-01`), or pass
`--since ""` to disable the floor. The cutoff is enforced both via Google News'
`after:` search operator and a hard date filter in the script (which also drops
undated items), so nothing older slips through.

Host `articles.json` in the **same folder** as the HTML (must be served over
http/https, not opened via file://, or the browser will block the fetch). The
page tries `articles.json` on load and falls back to the built-in snapshot if
it's missing; on success it updates the nav date to "Updated ... . live feed".

Automate the pull with cron, a GitHub Action, or any cloud scheduler, e.g.:

    # every second Monday at 06:00
    0 6 */14 * * cd /path/to/app && python fetch_feeds.py

### Sources — important

* **Google News** and **EIN "Automotive Industry Today"** expose RSS feeds and
  are wired into `fetch_feeds.py`. Google News mostly links out to publishers;
  the script keeps the original link and attributes the publisher.
* **NewsNow is not fetched.** Its terms prohibit scraping/redistribution and it
  has no reuse-friendly feed. Use it for manual monitoring only.
* Replace the EIN feed URL in `FEEDS` with the exact URL shown on the EIN
  automotive page (the placeholder there is illustrative).
* For anything client-facing, prefer adding **original/official feeds**
  (Reuters, ACEA, OEM newsrooms, regulators) — cleaner to reuse than aggregators.

### What `fetch_feeds.py` classifies (and what it doesn't)

The script derives, per item:
- **chain** — value-chain bucket, from keywords.
- **regions** — every relevant region (multi-match; no clear region → all three).
- **country** — a real country when the text names one (UAE, Saudi Arabia,
  Germany, China, etc.), falling back to a region label only when none is found.
  This is why the country tag no longer just repeats the region tag. Regional
  bodies (EU) are prioritised so an EU-policy story isn't mislabelled by an
  incidental country mention — though keyword rules aren't perfect, so review.
- **title** — cleaned of trailing publisher tags. Google News' standard
  " - Publisher" suffix is split off, and `clean_title()` additionally strips
  publisher names appended after a non-breaking/double space (e.g. the
  "…  Eurasia Review" case) or a stray dash/pipe.
- **impact / implication** — still emitted for backward compatibility, with a
  `REVIEW:` placeholder, but **no longer shown** by the front-end.

All classification is heuristic and a first pass. **Review chain, country and
region before publishing**, especially where a headline mentions several
places.

## Data caveats

The built-in snapshot is a point-in-time pull; summaries are AI-assembled from
real articles, so verify against the linked sources before circulating. Because
the items carry real dates, some value-chain sections (e.g. Distribution,
Aftermarket) may have no items under **Latest News** and appear only under
**Older News** — in a live fortnightly cycle via Option B each section fills as
fresh items arrive.

## Design / branding

The interface follows an internal design system (Arial throughout, a tight
neutral palette anchored on a single red accent, WCAG 2.1 AA contrast and focus
states). Before sharing externally, review all content for accuracy and run it
through your normal sign-off process.
