# ANNO MCP Server

An MCP server for a search of ANNO (AustriaN Newspapers Online), the historical newspaper archive of the Österreichische Nationalbibliothek (ÖNB), and for retrieval of its newspapers.

## Stack

- Python ≥3.12, uv, fastMCP ≥2.0.0, httpx ≥0.27.0

## Functions

- **A full-text search** with the boolean operators (AND, OR, NOT), exact phrases and a wildcard at the end of a word
- **Filters** for the date range, the title, the place, the language, the subject and the medium (newspaper against periodical)
- **Page-level KWIC snippets** that resolve a result to a page of an issue, with citation URLs and IIIF crops
- **An OCR text download** for each page or each issue, with a local cache
- **Pagination** at 10 results for each page, fixed by the server

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

`client.py` holds all the behaviour. `server.py` and `cli.py` are thin presentation layers over it, so the search semantics and the cache stay identical for each method of access. The CLI shows each filter without a condition. The MCP server hides them behind `--enable-advanced-search`.

## API Details

**ANNO publishes no API.** This client uses two services that have no documentation and no authentication.

**Search — the REST backend of the AnnoSearch application:**
- Base URL: `https://anno.onb.ac.at/anno-suche/rest`
- Endpoints: `/search/simple`, `/search/complex`, `/search/complex/config`, `/search/snippet`
- A person found these when they read the Angular bundle at `/anno-suche/main-<hash>.js`, which contains `apiUrl:"/anno-suche/rest"` and the four call sites. **The hash of the bundle changes at each release.** Find it again. Do not put it in the code.
- Response format: JSON, no key, no cookie

**Text retrieval — the "Text" button of the page viewer:**
- `https://anno.onb.ac.at/cgi-content/annoshow?text=<acronym>|<reference>|<page>`
- Response format: plain text, one page for each request

**Citation URLs:**
- `http://data.onb.ac.at/<owner>/<acronym><reference>?seite=<page>`, which redirects to the viewer

`robots.txt` is the standard Drupal file. It refuses `/search/` and `/admin/`, but not `/anno-suche/`, and it sets no `Crawl-delay`.

## Search Parameters

Each query goes through `/search/complex`, including a query with no filters. `/search/simple` accepts `query=` where `complex` accepts `text=`, but they report identical totals (both 1385 for `Hanussen`). Thus one code path removes each chance that the two become different in meaning.

| Parameter | Purpose |
|---|---|
| `text` | the query |
| `dateFrom` / `dateTo` | year or full date bounds |
| `language` | one of 24 codes, for example `ger`, `hun`, `cze`, `slo`, `ita`, `hrv` |
| `subject` | theme, for example `Tageszeitung` |
| `selectedFilters` | facet constraints, repeatable, `type:value` |
| `sort` | `date asc` / `date desc`; omit for relevance |
| `from` | 0-based record offset |
| `facets` | `true` |

That table is the full parameter surface, and it is authoritative and not a guess. The `searchComplex()` function of the Angular bundle builds its request from exactly `text`, `title`, `place`, `language`, `subject`, `dateFrom`, `dateTo`, `sort`, `selectedFilters`, `from` and `facets`, and from nothing else. The server accepts each other field name and ignores it.

## Facets

`/search/complex/config` is the endpoint that lists the facets, and one request answers "what can I filter on": `minDate` (1527-01-01), `maxDate`, and the full vocabulary of `titles` (1,566), `places` (231), `subjects` (65) and `languages` (24 codes, mapped to German names). The autocomplete fields of the search form are built from it, so consult it before you guess a value.

Each search with `facets=true` also returns `filterGroups`, which is the sidebar. There are exactly **six** groups and no more:

| Group | Label | Reached by |
|---|---|---|
| `TYPE` | Medium | `selectedFilters=type:journal` / `type:periodical` |
| `TITLE` | Titel | `selectedFilters=title:<acronym>` |
| `PLACE` | Erscheinungsort | `selectedFilters=place:<value>` |
| `LANGUAGE` | Sprache | `language=<code>` |
| `DATE` | Zeitraum | `dateFrom` / `dateTo` (finer than the five fixed buckets of the facet) |
| `SUBJECT_FACET` | Thema | `subject=<value>` |

This client shows all six. There is **no** facet for the provider, the collection, the publication frequency or the genre, because ANNO is an archive with one provider and a flat structure: the ÖNB owns everything in it. The frequency is not absent so much as folded into `subject`, whose vocabulary includes `Tageszeitung` and `Wochenzeitung`.

A group disappears from `filterGroups` after you filter on it. That is ordinary sidebar behaviour and not a signal.

## Result Ordering

`sort` takes `relevance` (default), `date_asc` or `date_desc`. This is the vocabulary of the client of each other archive. The client expresses relevance when it omits `sort`.

**ANNO filters the documents. It does not rank them.** This is different from Gallica, so `total_results` is a true count of the issues that match. Confirmed: `Hanussen` 1385, `Hanussen AND Hellseher` 398, `Hanussen NOT Hellseher` 987, and 398 + 987 = 1385 exactly. Thus you can give a total as a count, and an order by date is safe on each query. There is no relevance tail that hides the good material.

## Rate Limiting

A cross-process rate limiter (`ratelimit.py`) paces the requests. The default is **3s**, and `ANNO_MIN_REQUEST_INTERVAL` changes it. An in-process semaphore also limits the concurrency.

The ÖNB publishes no rate limit for ANNO, and the tests observed none during development: approximately fifty requests at three-second intervals produced no HTTP 429, no challenge page and no visible reduction in speed. That is an absence of evidence, not a documented permission, so the default matches the careful three seconds of the Gallica client.

**Why the limiter operates across processes, and not as an instance attribute.** Each call of the CLI is a separate process with its own instance, and we expect the agent to run several at the same time. Thus an instance attribute paces nothing. The limiter keeps its timestamp in `.rate-limit` inside the cache directory, with an exclusive `flock` to guard it.

## Caching

- **Cache:** the OCR text downloads
- **Do not cache:** the search results and the snippets (small, dynamic)
- **Location:** `$XDG_CACHE_HOME/anno-mcp/`, resolved by `paths.cache_dir()`; change it with `--cache-dir` or `ANNO_CACHE_DIR`

The cache keys are `<documentId>.txt` for a full issue and `<documentId>_p<N>.txt` for a single page, so the two do not collide.

The cache must not depend on the working directory. The CLI has a global installation, and a person runs it from whichever project they are in. A cache relative to the working directory would put the downloads in many places and would destroy the hit rate.

## Document Identifiers

Two forms, and code that assumes one form fails on the other:

| Id | Owner | Meaning |
|---|---|---|
| `ANNO_dmo19330626` | `ANNO` | Newspaper issue, `dmo`, 26 June 1933 |
| `ANNOP_klr19180004` | `ANNOP` | Periodical, `klr`, 1918 volume, item 4 |

The eight-digit reference is `YYYYMMDD` for a newspaper, but `YYYY` and a four-digit item number for a periodical. Thus it is **not** a date in general. `parse_document_id` matches it from the right, because a title acronym can itself contain digits.

The `uid` objects are also different. `ANNO` carries `annoDate.date`. `ANNOP` carries `year` and `itemId` and **no** `annoDate`. `_parse_document` handles both explicitly, and it raises an error on any third owner.

## Known behaviours and risks

- **Periodicals have no OCR text endpoint.** `annoshow?text=klr|19180004|5` answers HTTP 500 with a Perl error, `substr outside of string at /var/www/cgi-content/annoshow line 527`. This is not an incorrect reference on our side: the periodical viewer (`anno-plus`) has no "Text" button, and the newspaper viewer (`anno`) does. `download_text` refuses an `ANNOP_` id immediately, with an explanation, and it costs no request. The snippets operate correctly for the periodicals, so they stay usable.
- **A fetch of a full issue does not exist.** `annoshow?text=dmo|19330626` is HTTP 400, and so is a page range such as `|1-3`. The client must walk the pages one request at a time, which is why `get` has a price for each page and why `--page` is so important.
- **There is no field that gives the page count**, so the client finds the end of an issue when it walks into it. Any page past the end gives **HTTP 200 with the header line and no body**, not an HTTP 404. One empty page is not proof of the end, because a blank plate can occur in the middle of an issue. Thus `_fetch_issue_text` stops only after `EMPTY_PAGE_RUN_TO_STOP` consecutive empty pages, and it discards the empty pages at the end. The search results do carry `pageCount`, but `get <id>` alone has not seen them.
- **To remove the soft hyphen is not sufficient. The line break must go with it.** ANNO marks hyphenation with U+00AD immediately before the newline, so the raw text holds `ein\xad\nzige`. To delete only the soft hyphen leaves `ein\nzige`, which still does not match `einzige`. A local grep would then miss exactly the occurrences that the search index found. `_clean_ocr_text` joins the two parts. It deliberately leaves an ordinary hyphen at a line end alone, because `Hoch-Räthseln` is a real compound.
- **There is no `type=` field, and the server ignores one if you pass it.** You can reach the medium facet *only* through `selectedFilters=type:journal|periodical`. `text=Hanussen&type=journal` gives all 1385 results, not the 1339 newspapers. The server accepts an unrecognised field name and drops it, so a filter that looks applied can be absent. Confirmed: `selectedFilters=type:journal` gives 1339, `type:periodical` gives 46, and 1339 + 46 = 1385 exactly.
- **`type:journal` means newspaper, not journal.** The two facet values of ANNO are `journal` (displayed as *Zeitung*) and `periodical` (displayed as *Zeitschrift*), so the English reading of `journal` selects the opposite half of the archive from the half that it suggests. `FORMAT_VALUES` accepts `newspaper` as a synonym for exactly this reason. The division is precisely the `ANNO_`/`ANNOP_` owner division. The tests confirmed this when they walked two result pages of each: `type:journal` gave only `ANNO_`/Zeitung records, and `type:periodical` gave only `ANNOP_`/Zeitschrift records. Thus `medium="periodical"` selects exactly the set that `download_text` refuses.
- **An incorrect facet value gives HTTP 200 and zero results, not an error.** `selectedFilters=type:Zeitung` — the German label that ANNO displays itself — reports `totalHits: 0`, which is identical to a genuine empty result. Thus `_resolve_format` validates the value before it sends it. It does not pass a name through.
- **The facet values are exact, and a near-miss on `place` is worse than a spelling error.** The facet value for Prague is `Praha (Prag)`, and the `places` list of `/search/complex/config` holds `Prag` and `Praha ` as separate entries. That config list is the autocomplete vocabulary for the loose `place=` text field. It is **not** the facet vocabulary. `selectedFilters=place:Praha (Prag)` gives 45 results on `Hanussen`. `place:Prag` gives **1**, because `Prag` is also a real place value that is almost empty. A small number that looks credible is the failure, so a place value must come from the facet of a result itself.
- **`title=` and `place=` on `/search/complex` are not filters.** The help of ANNO states that a choice of a title "does not automatically search only in that title — instead the filter's text is used", which means that the server folds the value into the free-text query. Real filters go through repeated `selectedFilters=type:value` parameters. `Hanussen` limited with `selectedFilters=title:nwg` gives 97. The `title=` field gives a different number.
- **Endpoint drift gives HTTP 200 that carries the Angular HTML shell**, not an HTTP 404, because `/anno-suche/rest` is the private backend of a single-page application. Without detection this appears as an unclear JSON decode error. `_raise_for_html_shell` catches it and names the probable cause.
- **The first page of results holds 9 records, not 10.** The result numbers start at 1 and `from` starts at 0, so `from=0` gives results 1–9 and `from=10` gives 10–19. The client omits nothing, and the offset arithmetic `(page - 1) * 10` is correct.
- **The server gives a maximum of 10 snippets for each issue**, whatever the number of results. A document that reports `totalHits: 59` gives `totalHitsInSnippets: 10`.
- **A search record with an incorrect form raises an error.** To drop it would make the result list smaller while the reported total still counted it, which quietly under-reports a search. For a tool whose value is completeness, a loud failure is better than a quiet omission. An unknown `uid.owner` is exactly the case where a guess causes a quiet loss of data.
- **An empty result set is one empty page**, `total_pages: 1`, so each caller behaves the same here as for every other source.
- **IIIF has a gate after 1906, and the text does not.** `iiif.onb.ac.at/presentation/ANNO/<id>/manifest` answers for an issue before 1906 and gives HTTP 404 for a later one, with *"Older than 1906 (except bom) and not in ABO"*. This affects only the IIIF manifests. The OCR text and the hash-signed image crops in the snippet responses both operate for 1933 and 1948, so the client does not use IIIF.
- **`uv tool install --force .` can install an old wheel** when the version did not change. During development a correction to `_clean_ocr_text` appeared to have no effect until a person added `--reinstall`. Use `uv tool install --force --reinstall .` after you edit the code.
