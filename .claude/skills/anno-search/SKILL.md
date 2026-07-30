---
name: anno-search
description: Search ANNO (AustriaN Newspapers Online), the Österreichische Nationalbibliothek's historical newspaper archive, with the `anno` CLI. Use for German-language Austrian and Central European press — Vienna above all — and for the Austro-Hungarian coverage of touring performers.
---

# ANNO

The Austrian National Library's newspaper archive: roughly **28 million pages** across **1,600+ titles**, 1735 to the present, overwhelmingly German-language and Vienna-centred. Over **91%** of holdings are full-text searchable (the ÖNB's own figure).

Reach for it for the German-language press: Viennese dailies and the Austro-Hungarian provincial papers, plus satirical and trade weeklies. It is the natural counterpart to Gallica — where Gallica gives you the French reception of a touring performer, ANNO gives you the Central European one. For mentalism specifically it is exceptionally strong on the 1880s–1930s: Vienna was where the *Gedankenleser* toured and where Erik Jan Hanussen lived, worked and died.

## Commands

```sh
anno search "<query>" [--pages N|N-M|all] [--sort ORDER] [filters] [--json]
anno snippets <documentId> "<query>"   # which page of an issue, in context
anno get <documentId> [--page N]       # OCR text, prints path to the cached file
```

Filters for `search`: `--from-year`, `--to-year`, `--title ACRONYM`, `--place PLACE`, `--language CODE`, `--subject TEXT`, `--format {newspaper,periodical}`.

`--sort` takes `relevance` (default), `date_asc` or `date_desc`.

These six are **all** of ANNO's facets — the search sidebar has exactly six groups and every one is wired up. There is deliberately no `--provider`, `--collection` or `--genre` flag: ANNO is a single-provider archive (the ÖNB holds all of it) with a flat structure, so those facets do not exist rather than being unimplemented. Publication frequency is not a facet either; it lives inside `--subject`, as `Tageszeitung` and `Wochenzeitung`.

**Search resolves to an issue, not a page.** A result says *this issue of Der Morgen contains 59 hits*; `snippets` is what turns that into *page 7, and here is the sentence*. That middle step carries most of the value on this source, and it is usually enough to quote in a report without downloading anything:

```
$ anno snippets ANNO_dmo19330626 'Hanussen'
# ANNO_dmo19330626 — 6 occurrence(s) of Hanussen
    Seite 7  · ...ergab seine Identität: es war Erik Jan {Hanussen,} der Hellseher!...
        http://data.onb.ac.at/ANNO/dmo19330626?query=%22Hanussen%22&ref=anno-search&seite=7
```

Matched terms are marked in `{braces}`. Every snippet carries a citation URL pointing at that exact scanned page, which a human can open to check the quote.

## Query syntax

- Bare words are **ANDed**: `Hanussen Hellseher` requires both
- Boolean operators **must be uppercase**: `AND`, `OR`, `NOT`
- `"quoted phrases"` match exactly
- Trailing `*` is a wildcard: `Hanuss*`

Search in **German**. The collection is German-language, so an English query finds almost nothing: use `Gedankenleser`, `Hellseher`, `Telepath`, `Hypnotiseur`, `Wahrsager`, `Zauberkünstler`. Names usually carry across unchanged, but titles do not — the Austrian press writes `Professor Cumberland`, not `Mr. Cumberland` (and its OCR frequently writes `Air.` for `Mr.`, on which see below).

## The result count is a real count

**This is the important difference from Gallica, and it changes how the source is used.** ANNO filters rather than ranks, and its totals are honest:

| Query | Total |
|---|---|
| `Hanussen` | 1385 |
| `Hanussen AND Hellseher` | 398 |
| `Hanussen NOT Hellseher` | 987 |

398 + 987 = 1385 exactly. So:

- **A total can be quoted as a count.** "1,385 issues in ANNO mention Hanussen" is a true statement, unlike the equivalent claim on Gallica.
- **`--sort date_asc` is safe on any query**, because there is no relevance tail to bury the good material. Chronological reconstruction works straightforwardly here.
- **`--pages all` is meaningful**, subject to the cost below.

## Being exhaustive

**Ten results per page, fixed.** ANNO exposes no way to raise it, so sweeps are request-hungry: 1385 results is 139 requests, about seven minutes at the default pacing. This makes combining variants into a single query the right habit rather than a nicety — `(Gedankenleser OR Hellseher OR Telepath)` in one search beats three searches.

Narrow before sweeping. `--from-year`/`--to-year` work correctly (verified: a 1884–1888 filter returns only 1884–1886 material), and `--title` is a strict facet filter — `--title nwg` cuts `Hanussen` from 1385 to 97.

Title acronyms are the three-letter codes in the document ids: `nwg` (Neues Wiener Tagblatt), `nfp` (Neue Freie Presse), `nwj` (Neues Wiener Journal), `waz` (Wiener Allgemeine Zeitung), `dmo` (Der Morgen), `aze` (Arbeiter Zeitung), `fig` (Figaro), `flo` (Der Floh).

**The facets are catalogue metadata, so they are immune to the OCR damage below.** This is the reason to reach for them. A search *term* can be destroyed by Fraktur — letterspacing shatters a name, a long ſ becomes an f, a line break splits a word — but `--format`, `--title`, `--place`, `--language`, `--subject` and the year bounds are all read from the ÖNB's own catalogue and never from the page image. Narrowing by facet loses nothing; narrowing by adding a second search term can lose a great deal. So when a query is too broad, prefer a facet over an extra keyword.

### `--format`: newspapers or periodicals

Two values, and they partition the results exactly:

| Filter | `Hanussen` |
|---|---|
| (none) | 1385 |
| `--format newspaper` | 1339 |
| `--format periodical` | 46 |

1339 + 46 = 1385. The split is not cosmetic — it is exactly the `ANNO_`/`ANNOP_` split, so it tells you in advance which half of a result set you can download OCR text for:

- `--format newspaper` — *Zeitungen*, ids `ANNO_`, `anno get` works.
- `--format periodical` — *Zeitschriften*, ids `ANNOP_`, `anno get` refuses them and `snippets` is the only way in.

Both are useful. Use `--format newspaper` when you intend to download and read pages, and `--format periodical` to go straight at the illustrated, satirical and trade weeklies — which on this subject are often the richest material, and which a relevance-ordered sweep of 1385 newspaper-dominated results would bury.

ANNO's own value for *Zeitung* is the confusing `journal`; the CLI accepts both `newspaper` and `journal` for it, so pick `newspaper` and do not be misled if you see `journal` in the API. `--format Zeitung` is rejected with a message rather than silently returning zero.

### Facet values are verbatim, and a near-miss lies to you

`--place` is the one to watch. The value for Prague is `Praha (Prag)`, and `--place 'Praha (Prag)'` cuts `Hanussen` to 45. But `--place Prag` is *also* accepted and returns **1** — because `Prag` is a separate, nearly-empty place value in ANNO's index. A small plausible number, not an error. Copy place, subject and title values from a result you already have rather than translating or guessing them.

`--language` takes an ISO 639-2 code and ANNO holds 24 of them: `ger` dominates, then `hun`, `cze`, `slo`, `slv`, `hrv`, `ita`, `pol`, `heb`, `epo` and more.

## False positives to expect

Austrian OCR is Fraktur, and it fails in ways that are specific enough to be worth memorising.

**Letterspacing destroys names, and it does so silently.** This is the big one, and it loses hits rather than adding noise, so it will never announce itself. Nineteenth-century German typography emphasised personal names by letterspacing them (*Sperrsatz*), and the OCR reads each letter as a separate token. On a single 1884 page of the *Wiener Salonblatt*, real text renders as:

- `S ch l e s i n g e r` — Max Schlesinger, the article's author
- `S cb ü n b c r g e r` — the pianist Schönberger
- `R o f e` and `R o s e` — the violinist Rose, in two different manglings

A search for `Schlesinger` does not find that page. The defence is to expect it: when a search for a person is suspiciously thin, search instead for a distinctive *unspaced* word from the same context (`Gedankenleser`, the venue, the city), then read the page. Wildcards help with prefixes (`Hanuss*`) but cannot bridge inserted spaces.

**Long ſ read as f.** `R o f e` for *Rose* above; the pattern generalises, so `Hausse` may appear as `Haufse`, and any word with a medial s is a candidate.

**Hyphenation across line breaks.** ANNO marks it with a soft hyphen (U+00AD) before the newline. `anno get` joins those back up before caching, so downloaded text greps correctly — `einzige` and `Hanassen` come out whole. Snippets show the break honestly instead, as `{Ha} {nussen?"}`, which is a matched term split across two lines rather than two separate matches.

**Ordinary letter confusions**, all observed in real 1884 and 1933 text:

| OCR | Actual |
|---|---|
| `Air.` | Mr. |
| `Ouartett` | Quartett (Q→O) |
| `plötzlick` | plötzlich (h→k) |
| `antispiritislische` | antispiritistische (t→l) |
| `'Rummer`, `'Run` | Nummer, Nun (N→'R) |
| `tresflichen` | trefflichen (ff→sf) |
| `Racbtsalter` | Nachtfalter |
| `Wirnrr Lalonblatt` | Wiener Salonblatt |
| `Hanas­sen` | Hanussen (u→a) |

**Display type is often unreadable.** Headlines and mastheads set in decorative faces come back as noise: `Montag, SS. Funk 1SSS` is *Montag, 26. Juni 1933*, and `^05 v k k p k 7 k l LlÄÜILLA` was a 1948 banner. Body text is far better than headline text, so judge a page by its paragraphs.

**Umlauts.** Lowercase ä/ö/ü and ß survive well. Uppercase umlauts sometimes expand, so `ÖVP` appears as `OeVP` — worth ORing when searching for capitalised terms.

## Traps specific to this source

- **Periodicals have no OCR download.** Document ids beginning `ANNOP_` (`Zeitschrift`, shown in search output as *periodical — no OCR download*) are searchable and have working snippets, but ANNO exposes no text endpoint for them at all — the viewer has no "Text" button and the CGI crashes on their references. `anno get` refuses them with an explanation and costs no request. **Use `snippets` for periodicals**; they are fully usable that way, and the satirical and trade weeklies that live in this class are often the most interesting material. `--format periodical` / `--format newspaper` lets you decide which half you are looking at before you spend anything.
- **`get` is priced per page, not per document.** ANNO serves OCR one page at a time and offers no whole-issue endpoint, so `anno get` without `--page` costs one paced request per page — a 16-page issue is about a minute, a 104-page issue over five. Run `snippets` first and then `anno get <id> --page N`. This is the single biggest efficiency win available on this source.
- **Snippets are capped at 10 per issue** however many hits are reported. An issue reporting 59 hits returns a sample, not the lot. For heavily-covered issues, download the page.
- **The first result page holds 9, not 10.** Hit numbering is 1-based while the offset is 0-based, so page 1 is hits 1–9 and page 2 is hits 10–19. Nothing is skipped.
- **The API is undocumented, and endpoint drift is the one failure that needs you to fix code rather than change your query.** `/anno-suche/rest` is the private backend of ANNO's search app. If it is redeployed at a different path the server answers HTTP 200 with the app's HTML shell rather than a 404; the client detects that and raises with instructions rather than failing obscurely.

  If you hit it, it is a bug in the tool, not a transient fault and not a problem with your search — retrying and rewording both waste requests. Stop querying ANNO, **tell the user the source is unavailable**, and say so in any report you write, since a sweep that silently skipped a source is worse than one that admits it. Then fix it if you can: fetch `https://anno.onb.ac.at/anno-suche`, find the hashed `main-<HASH>.js` bundle it loads, search it for `apiUrl` and the nearby `/search/` paths, update `SEARCH_BASE_URL` in `anno-mcp`'s `client.py`, verify with one live search, and **commit the fix to the anno-mcp repository** so the next session does not have to rediscover it. The error message repeats these steps.
- Use `--refresh` to replace a cached copy you have reason to distrust.

## Cost

Rate-limited to **one request every three seconds** with single concurrency, shared across every process, so parallel subagents share one budget rather than each getting their own. Override with `ANNO_MIN_REQUEST_INTERVAL` only with reason.

The ÖNB publishes no rate limit for ANNO, and none was observed while this client was built — roughly fifty requests at three-second spacing drew no 429, no challenge page and no throttling. That is an absence of evidence rather than a documented allowance, so the pacing is deliberately cautious. **This is a free public service and the reading room it serves is real**; a sweep that looks thorough from here looks like scraping from theirs.

Budget in **pages fetched**, not documents. Search and snippets are one request each; `get` is one request *per page*. The practical ordering is therefore always search → snippets → `get --page N`, and going straight from a search result to a whole-issue `get` is the mistake that turns a two-minute task into a twenty-minute one.

Downloads are cached under `$XDG_CACHE_HOME/anno-mcp`, so the cost is paid once per page. If requests start failing or returning something other than what you asked for, stop and say so rather than retrying.
