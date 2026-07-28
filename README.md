# ANNO MCP Server

MCP server for [ANNO](https://anno.onb.ac.at/) (AustriaN Newspapers Online), the historical newspaper archive of the Österreichische Nationalbibliothek. Roughly **28 million pages** from over **1,600 titles**, 1735 to the present, overwhelmingly German-language, with over 91% of holdings full-text searchable.

- **search_anno**: Full-text search with AND/OR/NOT, exact phrases and wildcards. Results resolve to an issue, with the number of hits inside it.
- **get_snippets**: The page-level step — which page of an issue a term appears on, with the match in context and a citation URL for that exact page.
- **download_text**: OCR plain text for a newspaper issue or a single page of it, cached locally.
- **advanced_search_anno**: Search with date, title, place, language and subject filters.

There are two ways to use it: an **MCP server** for clients that speak MCP, and an **`anno` CLI** for agents driven through a shell. Both share one client, one cache and one set of behaviours. The CLI is what the bundled `anno-search` skill uses, and it exposes every filter unconditionally rather than hiding them behind an install flag.

ANNO publishes no API. This client talks to the REST backend of the AnnoSearch app at `anno.onb.ac.at/anno-suche/rest`, found by reading the app's JavaScript bundle, plus the `annoshow` CGI that the page viewer's "Text" button opens. Both are unauthenticated and need no key — but nobody has promised to keep them stable, so the client detects endpoint drift explicitly rather than failing obscurely.

## Installation

### Install the code

```bash
uv sync
```

### Install the CLI

```bash
uv tool install .        # puts `anno` on your PATH
```

### Install to MCP CLIs

Installs to Claude Code, Codex CLI, and Gemini CLI:

```bash
# Basic installation (search_anno + get_snippets + download_text)
uv run anno-mcp-install

# With advanced search enabled (adds advanced_search_anno)
uv run anno-mcp-install --enable-advanced-search
```

Verify the installation:

```bash
claude mcp list   # For Claude Code
codex mcp list    # For Codex CLI
gemini mcp list   # For Gemini CLI
```

## Usage

### CLI

```bash
anno search 'Weltausstellung'                                    # first page, best matches first
anno search '"Wiener Weltausstellung"' --from-year 1873 --to-year 1873
anno search 'Ringstraße Neubau' --from-year 1865 --to-year 1875 --sort date_asc
anno search 'Semmeringbahn' --place Wien --title nfp --pages all
anno snippets ANNO_nfp18731202 'Ringstraße'                      # which page, in context
anno get ANNO_nfp18731202 --page 3                               # cached OCR text path
```

The workflow is search → `snippets` to find the page and judge it cheaply → `get` only what is worth reading. Add `--json` for machine-readable output.

**Search resolves to an issue, not a page.** A result says "this issue of the *Neue Freie Presse* contains 7 hits"; `snippets` is what turns that into "page 3, and here is the sentence". That middle step is where most of the value is, because it is also enough to quote in a report.

**Result totals are true match counts.** Unlike Gallica, ANNO filters rather than ranks: `Weltausstellung` reports 153,799, `Weltausstellung AND Ringstraße` 19,958, `Weltausstellung NOT Ringstraße` 133,841 — and 19,958 + 133,841 = 153,799 exactly. A total can therefore be quoted as a count, and `--sort date_asc` is safe on any query you intend to sweep.

**Ten results per page, fixed.** ANNO offers no way to raise it, so sweeps are request-hungry: 1,385 results is 139 requests. Combining variants into one `(A OR B OR C)` query is how you keep that down.

Downloads are cached in `$XDG_CACHE_HOME/anno-mcp` (override with `--cache-dir` or `ANNO_CACHE_DIR`). The cache location does not depend on the working directory, so the CLI can be run from anywhere.

Requests are paced one every 3 seconds by default, overridable with `ANNO_MIN_REQUEST_INTERVAL`. The ÖNB publishes no rate limit and none was observed in testing, so this is caution rather than a measured ceiling.

**`get` is the expensive call, and unusually so here.** ANNO serves OCR one page at a time — a whole-issue download costs one paced request per page, so a 104-page issue is over five minutes of requests. Use `--page` once `snippets` has told you which page you want. Periodicals (`ANNOP_`) have no text endpoint at all and `get` refuses them with an explanation; their snippets work normally.

### MCP server

Run the server directly:

```bash
uv run anno-mcp
```

Test with MCP Inspector:

```bash
uv run fastmcp dev src/anno_mcp/server.py
```
