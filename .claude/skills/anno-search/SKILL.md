---
name: anno-search
description: Search ANNO (AustriaN Newspapers Online), the historical newspaper archive of the Österreichische Nationalbibliothek, with the `anno` CLI. Use it for the German-language Austrian and Central European press — Vienna above all — and for the Austro-Hungarian reports about performers who travelled.
---

# ANNO

The newspaper archive of the Austrian National Library holds approximately **28 million pages** across more than **1,600 titles**, from 1735 to the present day. It is almost all German-language, and Vienna is its centre. ANNO can do a full-text search on more than **91%** of the holdings (the ÖNB gives this figure itself).

Use it for the German-language press: the Viennese daily papers and the Austro-Hungarian provincial papers, and also the satirical and trade weekly papers. It is the natural counterpart to Gallica. Gallica gives you the French reception of a performer who travelled, and ANNO gives you the Central European reception. For mentalism it is exceptionally strong on the 1880s to the 1930s. Vienna was where the *Gedankenleser* travelled and performed, and where Erik Jan Hanussen lived, worked and died.

## Commands

```sh
anno search "<query>" [--pages N|N-M|all] [--sort ORDER] [filters] [--json]
anno snippets <documentId> "<query>"   # which page of an issue, in context
anno get <documentId> [--page N]       # OCR text, prints path to the cached file
```

The filters for `search` are `--from-year`, `--to-year`, `--title ACRONYM`, `--place PLACE`, `--language CODE`, `--subject TEXT` and `--format {newspaper,periodical}`.

`--sort` takes `relevance` (default), `date_asc` or `date_desc`.

These six filters are **all** of the facets of ANNO. The search sidebar has exactly six groups, and the client uses each one. There is no `--provider` flag, no `--collection` flag and no `--genre` flag, by decision. ANNO is an archive with one provider (the ÖNB owns all of it) and a flat structure, so those facets do not exist. The client does not omit them. ANNO does not have them.

The publication frequency is also not a facet. It is inside `--subject`, as `Tageszeitung` and `Wochenzeitung`.

**A search resolves to an issue, not to a page.** A result says *this issue of Der Morgen holds 59 matches*. `snippets` changes that into *page 7, and here is the sentence*. That middle step holds most of the value on this source, and it is usually sufficient to quote in a report with no download:

```
$ anno snippets ANNO_dmo19330626 'Hanussen'
# ANNO_dmo19330626 — 6 occurrence(s) of Hanussen
    Seite 7  · ...ergab seine Identität: es war Erik Jan {Hanussen,} der Hellseher!...
        http://data.onb.ac.at/ANNO/dmo19330626?query=%22Hanussen%22&ref=anno-search&seite=7
```

The tool marks the matched terms with `{braces}`. Each snippet carries a citation URL that points at that exact scanned page, and a human can open it to examine the quotation.

## Query syntax

- The tool joins bare words with **AND**: `Hanussen Hellseher` needs both
- The boolean operators **must be uppercase**: `AND`, `OR`, `NOT`
- `"quoted phrases"` match exactly
- A `*` at the end is a wildcard: `Hanuss*`

Search in **German**. The collection is German-language, so a query in English finds almost nothing. Use `Gedankenleser`, `Hellseher`, `Telepath`, `Hypnotiseur`, `Wahrsager` and `Zauberkünstler`. Names usually stay the same, but titles do not. The Austrian press writes `Professor Cumberland`, not `Mr. Cumberland`. Its OCR also writes `Air.` for `Mr.` frequently, as the section below shows.

## The result count is a real count

**This is the important difference from Gallica, and it changes how you use the source.** ANNO filters the documents. It does not rank them. Its totals are honest:

| Query | Total |
|---|---|
| `Hanussen` | 1385 |
| `Hanussen AND Hellseher` | 398 |
| `Hanussen NOT Hellseher` | 987 |

398 + 987 = 1385 exactly. Thus:

- **You can give a total as a count.** "1,385 issues in ANNO mention Hanussen" is a true statement. The equivalent statement on Gallica is not true.
- **`--sort date_asc` is safe on each query**, because there is no relevance tail that hides the good material. A chronological reconstruction is simple here.
- **`--pages all` has a meaning**, but see the cost below.

## How to be complete

**There are ten results on each page, and this number is fixed.** ANNO has no method to increase it, so a full search needs many requests. 1385 results is 139 requests, or approximately seven minutes at the default rate. Thus one query that holds each variant is the correct habit, and not only a small improvement: `(Gedankenleser OR Hellseher OR Telepath)` in one search is better than three searches.

Make the query more narrow before you collect the results. `--from-year` and `--to-year` operate correctly (confirmed: a filter of 1884–1888 gives only material from 1884 to 1886). `--title` is a strict facet filter: `--title nwg` reduces `Hanussen` from 1385 to 97.

The title acronyms are the three-letter codes in the document identifiers: `nwg` (Neues Wiener Tagblatt), `nfp` (Neue Freie Presse), `nwj` (Neues Wiener Journal), `waz` (Wiener Allgemeine Zeitung), `dmo` (Der Morgen), `aze` (Arbeiter Zeitung), `fig` (Figaro) and `flo` (Der Floh).

**The facets are catalogue metadata, so the OCR errors below do not affect them.** This is the reason to use them. Fraktur can destroy a search *term*: letterspacing breaks a name, a long ſ becomes an f, and a line break divides a word. But `--format`, `--title`, `--place`, `--language`, `--subject` and the year limits come from the catalogue of the ÖNB, never from the page image. To make a query narrow with a facet loses nothing. To make a query narrow with a second search term can lose much. Thus, when a query is too broad, use a facet in place of one more keyword.

### `--format`: newspapers or periodicals

There are two values, and they divide the results exactly:

| Filter | `Hanussen` |
|---|---|
| (none) | 1385 |
| `--format newspaper` | 1339 |
| `--format periodical` | 46 |

1339 + 46 = 1385. This division is important, because it is exactly the `ANNO_` and `ANNOP_` division. Thus it tells you in advance which half of a result set has an OCR download:

- `--format newspaper` — *Zeitungen*, identifiers `ANNO_`, and `anno get` operates.
- `--format periodical` — *Zeitschriften*, identifiers `ANNOP_`. `anno get` refuses them, and `snippets` is the only method of access.

Both values are useful. Use `--format newspaper` when you intend to download and read pages. Use `--format periodical` to go directly to the illustrated, satirical and trade weekly papers. On this subject those papers frequently hold the richest material, and a search of 1385 mostly-newspaper results in relevance order would hide them.

The value of ANNO for *Zeitung* is `journal`, which is confusing. The CLI accepts both `newspaper` and `journal` for it. Use `newspaper`, and do not let `journal` in the API confuse you. `--format Zeitung` gives a message of rejection. It does not give zero results without a message.

### The facet values are exact, and a near-miss gives an incorrect answer

`--place` is the value to watch. The value for Prague is `Praha (Prag)`, and `--place 'Praha (Prag)'` reduces `Hanussen` to 45. But `--place Prag` is *also* accepted, and it gives **1**, because `Prag` is a separate and almost empty place value in the index of ANNO. The result is a small credible number, not an error. Copy the place, subject and title values from a result that you already have. Do not translate them, and do not guess them.

`--language` takes an ISO 639-2 code, and ANNO holds 24 of them: `ger` is dominant, then `hun`, `cze`, `slo`, `slv`, `hrv`, `ita`, `pol`, `heb`, `epo` and more.

## False positives to expect

The Austrian OCR is Fraktur, and it fails in ways that are specific enough to learn.

**Letterspacing destroys names, and it gives no message.** This is the largest problem. It loses results. It does not add incorrect results, so it never announces itself. German typography of the 19th century gave emphasis to personal names with letterspacing (*Sperrsatz*), and the OCR reads each letter as a separate token. On one 1884 page of the *Wiener Salonblatt*, real text becomes:

- `S ch l e s i n g e r` — Max Schlesinger, the author of the article
- `S cb ü n b c r g e r` — the pianist Schönberger
- `R o f e` and `R o s e` — the violinist Rose, in two different forms

A search for `Schlesinger` does not find that page. The defence is to expect this. When a search for a person gives very few results, search instead for a distinctive word from the same context that has no letterspacing (`Gedankenleser`, the theatre, the city). Then read the page. Wildcards help with a prefix (`Hanuss*`), but they cannot cross the spaces that the OCR inserted.

**A long ſ reads as f.** `R o f e` for *Rose* above. The pattern is general, so `Hausse` can appear as `Haufse`, and each word with an s in the middle is a candidate.

**Hyphenation across a line break.** ANNO marks it with a soft hyphen (U+00AD) before the newline. `anno get` joins these before it writes the cache, so a grep of the downloaded text operates correctly: `einzige` and `Hanassen` come out complete. The snippets show the break as it is, as `{Ha} {nussen?"}`. This is one matched term divided across two lines, not two separate matches.

**Ordinary confusions between letters**, each one observed in real text of 1884 and 1933:

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

**Display type is frequently unreadable.** Headlines and mastheads in decorative faces come back as noise. `Montag, SS. Funk 1SSS` is *Montag, 26. Juni 1933*, and `^05 v k k p k 7 k l LlÄÜILLA` was a banner of 1948. The body text is much better than the headline text, so judge a page by its paragraphs.

**Umlauts.** The lowercase ä, ö, ü and ß survive well. An uppercase umlaut sometimes expands, so `ÖVP` appears as `OeVP`. Add an OR clause for this when you search for a term in capital letters.

## Risks specific to this source

- **Periodicals have no OCR download.** The document identifiers that start with `ANNOP_` (*Zeitschrift*, shown in the search output as *periodical — no OCR download*) have a search and working snippets. But ANNO has no text endpoint for them at all: the viewer has no "Text" button, and the CGI script fails on their references. `anno get` refuses them with an explanation, and it costs no request. **Use `snippets` for the periodicals.** They are fully usable in this way, and the satirical and trade weekly papers in this class frequently hold the most interesting material. `--format periodical` and `--format newspaper` let you select the half that you look at before you spend anything.
- **`get` has a price for each page, not for each document.** ANNO sends the OCR one page at a time, and it has no endpoint for a full issue. Thus `anno get` without `--page` costs one paced request for each page. A 16-page issue takes approximately one minute, and a 104-page issue more than five minutes. Run `snippets` first, then `anno get <id> --page N`. This is the largest single improvement in efficiency on this source.
- **The tool gives a maximum of 10 snippets for each issue**, whatever the number of matches. An issue that reports 59 matches gives a sample, not all of them. For an issue with many matches, download the page.
- **The first page of results holds 9 results, not 10.** The result numbers start at 1, and the offset starts at 0, so page 1 is results 1–9 and page 2 is results 10–19. The tool omits nothing.
- **The API has no documentation, and endpoint drift is the one failure that needs a correction in code and not a different query.** `/anno-suche/rest` is the private backend of the search application of ANNO. If the ÖNB moves it to a different path, the server answers HTTP 200 with the HTML shell of the application, not HTTP 404. The client detects this and raises an error with instructions. It does not fail in an unclear way.

  **Stop all requests to ANNO.** This is a fault in the tool. It is not a temporary failure, and it is not a problem with your search. A second attempt and a new query both waste requests.

  **Tell the user that the source is not available.** Write this in each report. A search that quietly omits a source is worse than a search that reports the omission.

  Then correct the fault if you can. Do these steps:

  1. Fetch `https://anno.onb.ac.at/anno-suche`.
  2. Find the `main-<HASH>.js` bundle that the page loads. The hash changes at each release.
  3. Find `apiUrl` in that bundle. Read the `/search/` paths near `apiUrl`.
  4. Change `SEARCH_BASE_URL` in `client.py` of `anno-mcp`.
  5. Do one live search to confirm the correction.
  6. **Commit the correction to the anno-mcp repository**, so that the next session does not do this work again.

  The error message repeats these steps.
- Use `--refresh` to replace a copy in the cache that you have a reason to doubt.

## Cost

The client permits **one request every three seconds**, with one request at a time. All processes share this limit, so parallel subagents share one budget. No subagent receives its own budget. Change the interval with `ANNO_MIN_REQUEST_INTERVAL` only when you have a reason.

The ÖNB publishes no rate limit for ANNO, and the tests during the build of this client observed none. Approximately fifty requests at three-second intervals gave no HTTP 429, no challenge page and no reduction in speed. That is an absence of evidence, not a documented permission, so the rate is deliberately careful. **This is a free public service, and real persons use the reading room of the ÖNB.** A search that looks thorough to you looks like data collection to the ÖNB.

Plan the budget in **pages that you fetch**, not in documents. A search and a snippets command are one request each. `get` is one request *for each page*. Thus the correct order is always search → snippets → `get --page N`. To go directly from a search result to a `get` of a full issue is the error that changes a two-minute task into a twenty-minute task.

The client keeps the downloads in a cache under `$XDG_CACHE_HOME/anno-mcp`, so you pay the cost one time for each page. If the requests start to fail, or if they give content that you did not ask for, stop and tell the user. Do not send the request again.
