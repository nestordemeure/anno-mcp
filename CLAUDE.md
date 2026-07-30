# ANNO MCP Server

MCP server for searching and retrieving newspapers from ANNO (AustriaN Newspapers Online), the historical newspaper archive of the Österreichische Nationalbibliothek (ÖNB).

## Stack

- Python ≥3.12, uv, fastMCP ≥2.0.0, httpx ≥0.27.0

## Functionality

- **Fulltext search** with boolean operators (AND, OR, NOT), exact phrases and trailing wildcards
- **Filters** for date range, title, place, language, subject and medium (newspaper vs periodical)
- **Page-level KWIC snippets** resolving a hit to a page of an issue, with citation URLs and IIIF crops
- **OCR text download** per page or per issue, with local caching
- **Pagination** at a server-fixed 10 results per page

## Structure

```
anno-mcp/
├── .claude/skills/anno-search/   # Skill documenting the CLI
├── src/anno_mcp/
│   ├── __init__.py
│   ├── client.py           # API client + caching
│   ├── cli.py              # `anno` command-line interface
│   ├── paths.py            # Cache location resolution
│   ├── ratelimit.py        # Cross-process request pacing
│   ├── server.py           # FastMCP tools
│   └── install.py          # MCP server installer
├── pyproject.toml
└── CLAUDE.md               # This file
```

`client.py` holds all the behaviour; `server.py` and `cli.py` are thin presentation layers over it, so search semantics and caching stay identical no matter how it is called. The CLI exposes every filter unconditionally, where the MCP server hides them behind `--enable-advanced-search`.

## API Details

**ANNO publishes no API.** What this client talks to are two undocumented but unauthenticated services:

**Search — the AnnoSearch app's REST backend:**
- Base URL: `https://anno.onb.ac.at/anno-suche/rest`
- Endpoints: `/search/simple`, `/search/complex`, `/search/complex/config`, `/search/snippet`
- Discovered by reading the Angular bundle at `/anno-suche/main-<hash>.js`, which contains `apiUrl:"/anno-suche/rest"` and the four call sites. **The bundle hash changes on redeploy** — rediscover it rather than hardcoding it.
- Response format: JSON, no key, no cookie

**Text retrieval — the page viewer's "Text" button:**
- `https://anno.onb.ac.at/cgi-content/annoshow?text=<acronym>|<reference>|<page>`
- Response format: plain text, one page per request

**Citation URLs:**
- `http://data.onb.ac.at/<owner>/<acronym><reference>?seite=<page>`, redirecting to the viewer

`robots.txt` is stock Drupal. It disallows `/search/` and `/admin/`, but not `/anno-suche/`, and sets no `Crawl-delay`.

## Search Parameters

Everything goes through `/search/complex`, including unfiltered queries. `/search/simple` accepts `query=` where `complex` accepts `text=`, but they report identical totals (both 1385 for `Hanussen`), so a single code path removes any chance of the two drifting apart in meaning.

| Parameter | Purpose |
|---|---|
| `text` | the query |
| `dateFrom` / `dateTo` | year or full date bounds |
| `language` | one of 24 codes, e.g. `ger`, `hun`, `cze`, `slo`, `ita`, `hrv` |
| `subject` | theme, e.g. `Tageszeitung` |
| `selectedFilters` | facet constraints, repeatable, `type:value` |
| `sort` | `date asc` / `date desc`; omit for relevance |
| `from` | 0-based record offset |
| `facets` | `true` |

That table is the whole parameter surface, and it is authoritative rather than guessed: the Angular bundle's `searchComplex()` builds its request from exactly `text`, `title`, `place`, `language`, `subject`, `dateFrom`, `dateTo`, `sort`, `selectedFilters`, `from` and `facets`, and nothing else. Any other field name is accepted and ignored.

## Facets

`/search/complex/config` is the facet-listing endpoint and one request answers "what can be filtered on": `minDate` (1527-01-01), `maxDate`, and the full vocabulary of `titles` (1,566), `places` (231), `subjects` (65) and `languages` (24 codes, mapped to German names). It is what the search form's autocompletes are built from, so it should be consulted before guessing a value.

Every search with `facets=true` also returns `filterGroups`, the sidebar. There are exactly **six** groups and no more:

| Group | Label | Reached by |
|---|---|---|
| `TYPE` | Medium | `selectedFilters=type:journal` / `type:periodical` |
| `TITLE` | Titel | `selectedFilters=title:<acronym>` |
| `PLACE` | Erscheinungsort | `selectedFilters=place:<value>` |
| `LANGUAGE` | Sprache | `language=<code>` |
| `DATE` | Zeitraum | `dateFrom` / `dateTo` (finer than the facet's five fixed buckets) |
| `SUBJECT_FACET` | Thema | `subject=<value>` |

All six are exposed by this client. There is **no** facet for provider, collection, publication frequency or genre, because ANNO is a single-provider archive with a flat structure — the ÖNB holds everything in it. Frequency is not missing so much as folded into `subject`, whose vocabulary includes `Tageszeitung` and `Wochenzeitung`.

A group vanishes from `filterGroups` once it is filtered on, which is ordinary sidebar behaviour and not a signal.

## Result Ordering

`sort` accepts `relevance` (default), `date_asc` or `date_desc`, sharing the vocabulary of the sibling archive clients. Relevance is expressed by omitting `sort` altogether.

Unlike Gallica, **ANNO filters rather than ranks**, so `total_results` is a true count of matching issues. Verified: `Hanussen` 1385, `Hanussen AND Hellseher` 398, `Hanussen NOT Hellseher` 987, and 398 + 987 = 1385 exactly. A total may therefore be quoted as a count, and date ordering is safe on any query — there is no relevance tail to bury the good material.

## Rate Limiting

Requests are spaced by a cross-process rate limiter (`ratelimit.py`), default **3s**, overridable with `ANNO_MIN_REQUEST_INTERVAL`, on top of an in-process semaphore limiting concurrency.

The ÖNB publishes no rate limit for ANNO and none was observed during development: roughly fifty requests at three-second spacing produced no 429, no challenge page and no visible throttling. That is an absence of evidence rather than a documented allowance, so the default matches the Gallica client's conservative three seconds.

**Why cross-process rather than an instance attribute.** Every CLI invocation is a separate process with its own instance, and callers are expected to fan work out across several at once, so an instance attribute paces nothing. The limiter keeps its timestamp in `.rate-limit` inside the cache directory, guarded by an exclusive `flock`.

## Caching

- **Cache:** OCR text downloads
- **Don't cache:** Search results and snippets (small, dynamic)
- **Location:** `$XDG_CACHE_HOME/anno-mcp/`, resolved by `paths.cache_dir()`; override with `--cache-dir` or `ANNO_CACHE_DIR`

Cache keys are `<documentId>.txt` for a whole issue and `<documentId>_p<N>.txt` for a single page, so the two do not collide.

The cache must not depend on the working directory: the CLI is installed globally and run from whatever project the researcher is in, so a CWD-relative cache would scatter downloads and destroy the hit rate.

## Document Identifiers

Two shapes, and code that assumes one crashes on the other:

| Id | Owner | Meaning |
|---|---|---|
| `ANNO_dmo19330626` | `ANNO` | Newspaper issue, `dmo`, 26 June 1933 |
| `ANNOP_klr19180004` | `ANNOP` | Periodical, `klr`, 1918 volume, item 4 |

The eight-digit reference is `YYYYMMDD` for newspapers but `YYYY` + a four-digit item number for periodicals, so it is **not** a date in general. `parse_document_id` matches it from the right, because a title acronym may itself contain digits.

The corresponding `uid` objects differ too: `ANNO` carries `annoDate.date`, `ANNOP` carries `year` and `itemId` and **no** `annoDate`. `_parse_document` handles both explicitly and raises on any third owner.

## Gotchas

- **Periodicals have no OCR text endpoint at all.** `annoshow?text=klr|19180004|5` answers HTTP 500 with a Perl `substr outside of string at /var/www/cgi-content/annoshow line 527`. This is not a bad reference on our side: the periodical viewer (`anno-plus`) has no "Text" button, where the newspaper viewer (`anno`) does. `download_text` refuses `ANNOP_` ids up front with an explanation and costs no request. Snippets work fine for periodicals, so they remain usable.
- **A whole-issue fetch does not exist.** `annoshow?text=dmo|19330626` is HTTP 400, and so is a page range like `|1-3`. Pages must be walked one request at a time, which is why `get` is priced per page and why `--page` matters so much.
- **There is no page-count field to walk against**, so the end of an issue is found by walking into it. Any page past the end returns **HTTP 200 with the header line and no body** — not a 404. A single empty page is not proof of the end, because blank plates occur mid-issue, so `_fetch_issue_text` stops only after `EMPTY_PAGE_RUN_TO_STOP` consecutive empties and discards trailing ones. Search results do carry `pageCount`, but `get <id>` alone has not seen them.
- **Stripping the soft hyphen is not enough — the line break has to go with it.** ANNO marks hyphenation with U+00AD immediately before the newline, so the raw text holds `ein\xad\nzige`. Deleting only the soft hyphen leaves `ein\nzige`, which still does not match `einzige`, so a local grep would miss exactly the occurrences the search index found. `_clean_ocr_text` joins the two. Ordinary hyphens at a line end are deliberately left alone, since `Hoch-Räthseln` is a real compound.
- **There is no `type=` field, and passing one is silently ignored.** The medium facet is reachable *only* through `selectedFilters=type:journal|periodical`. `text=Hanussen&type=journal` returns all 1385 hits, not the 1339 newspapers — an unrecognised field name is accepted and dropped, so a filter that looks applied may not be. Verified: `selectedFilters=type:journal` gives 1339, `type:periodical` gives 46, and 1339 + 46 = 1385 exactly.
- **`type:journal` means newspaper, not journal.** ANNO's two facet values are `journal` (displayed *Zeitung*) and `periodical` (displayed *Zeitschrift*), so the English reading of `journal` selects the opposite half of the archive from what it suggests. `FORMAT_VALUES` accepts `newspaper` as a synonym for exactly this reason. The split is precisely the `ANNO_`/`ANNOP_` owner split — verified by walking two result pages of each, where `type:journal` returned only `ANNO_`/Zeitung records and `type:periodical` only `ANNOP_`/Zeitschrift — so `medium="periodical"` selects exactly the set `download_text` refuses.
- **A wrong facet value returns HTTP 200 and zero hits, not an error.** `selectedFilters=type:Zeitung` — ANNO's own displayed German label — reports `totalHits: 0`, indistinguishable from a genuine empty result. `_resolve_format` therefore validates before sending rather than passing a name through.
- **Facet values are verbatim, and a near-miss on `place` is worse than a typo.** The facet value for Prague is `Praha (Prag)`, while `/search/complex/config`'s `places` list holds `Prag` and `Praha ` as separate entries — the config list is the autocomplete vocabulary for the loose `place=` text field, **not** the facet vocabulary. `selectedFilters=place:Praha (Prag)` gives 45 hits on `Hanussen`; `place:Prag` gives **1**, because `Prag` is also a real but nearly empty place value. A plausible-looking small number is the failure mode, so place values must be copied from a result's own facet.
- **`title=` and `place=` on `/search/complex` are not filters.** ANNO's own help states that choosing a title "does not automatically search only in that title — instead the filter's text is used", i.e. the value is folded into the free-text query. Real filtering goes through repeated `selectedFilters=type:value` parameters. `Hanussen` restricted via `selectedFilters=title:nwg` gives 97; the `title=` field gives something else entirely.
- **Endpoint drift returns HTTP 200 carrying the Angular HTML shell**, not a 404, because `/anno-suche/rest` is the private backend of a single-page app. Undetected this surfaces as an opaque JSON decode error. `_raise_for_html_shell` catches it and names the likely cause.
- **The first result page holds 9 records, not 10.** Hit numbering is 1-based while `from` is 0-based, so `from=0` yields hits 1–9 and `from=10` yields 10–19. Nothing is skipped; the offset arithmetic `(page - 1) * 10` is correct.
- **Snippets are capped at 10 per issue** regardless of the hit count — a document reporting `totalHits: 59` returns `totalHitsInSnippets: 10`.
- **A malformed search record raises.** Dropping it would shrink the result list while the reported total still counted it, silently under-reporting a search. For a tool whose value rests on exhaustivity, a loud failure beats a quiet omission — and an unknown `uid.owner` is exactly the case where guessing causes silent data loss.
- **An empty result set is one empty page**, `total_pages: 1`, so callers behave the same here as for any other source.
- **IIIF is gated after 1906, but text is not.** `iiif.onb.ac.at/presentation/ANNO/<id>/manifest` answers pre-1906 issues and 404s later ones with *"Older than 1906 (except bom) and not in ABO"*. This affects only IIIF manifests. OCR text and the hash-signed image crops returned in snippet responses both work for 1933 and 1948, so the client does not use IIIF at all.
- **`uv tool install --force .` can install a stale wheel** when the version has not changed. During development a fix to `_clean_ocr_text` appeared not to take effect until `--reinstall` was added. Use `uv tool install --force --reinstall .` after editing.
