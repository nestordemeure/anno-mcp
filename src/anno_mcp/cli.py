"""Command-line interface for ANNO search.

A thin wrapper over :class:`AnnoClient` that formats results for reading in a
terminal or by an agent driving the command through a shell. Output is compact
and greppable by default; ``--json`` emits the raw client structures.

Unlike the MCP server, which hides filtering behind an install-time flag, every
filter is available here.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from .client import DEFAULT_SORT, RESULTS_PER_PAGE, SORT_ORDERS, AnnoClient
from .paths import cache_dir

PROGRAM_NAME = "anno"


class PageRange:
    """A 1-indexed, inclusive range of result pages. ``last is None`` means all."""

    def __init__(self, first: int, last: int | None) -> None:
        self.first = first
        self.last = last

    def contains(self, page: int) -> bool:
        return page >= self.first and (self.last is None or page <= self.last)

    def __str__(self) -> str:
        if self.last is None:
            return f"{self.first}-all"
        if self.last == self.first:
            return str(self.first)
        return f"{self.first}-{self.last}"


def parse_page_range(value: str) -> PageRange:
    """Parse a ``--pages`` value: ``3``, ``2-5`` or ``all``."""
    text = value.strip().lower()

    if text == "all":
        return PageRange(1, None)

    try:
        if "-" in text:
            first_text, _, last_text = text.partition("-")
            first, last = int(first_text), int(last_text)
        else:
            first = last = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected a page number, a range like 2-5, or 'all'; got {value!r}"
        ) from None

    if first < 1:
        raise argparse.ArgumentTypeError(f"page numbers start at 1; got {value!r}")
    if last < first:
        raise argparse.ArgumentTypeError(f"page range runs backwards: {value!r}")

    return PageRange(first, last)


def format_document(position: int, document: dict[str, Any]) -> str:
    """Render one search result.

    Search resolves to an issue, not a page - ``anno snippets`` is what turns an
    issue into pages, so the hit count is shown here to say how much is waiting.
    """
    lines = []

    when = document.get("date") or (
        str(document["year"]) if document.get("year") else "n.d."
    )
    lines.append(f"[{position}] {document['identifier']}  ({when})")
    lines.append(f"    {document.get('title') or 'Untitled'}")

    descriptors: list[str] = []
    if document.get("type"):
        descriptors.append(str(document["type"]))
    if places := document.get("places"):
        descriptors.append(", ".join(places))
    if languages := document.get("languages"):
        descriptors.append(", ".join(languages))
    if descriptors:
        lines.append(f"    {' · '.join(descriptors)}")

    counts = []
    if (hits := document.get("hits_in_document")) is not None:
        counts.append(f"{hits} hit(s) in issue")
    if (pages := document.get("page_count")) is not None:
        counts.append(f"{pages} page(s)")
    if document.get("is_periodical"):
        counts.append("periodical — no OCR download")
    if counts:
        lines.append(f"    {' · '.join(counts)}")

    if url := document.get("url"):
        lines.append(f"    {url}")
    return "\n".join(lines)


async def run_search(args: argparse.Namespace) -> int:
    """Fetch the requested pages, streaming results as each page arrives."""
    client = AnnoClient(cache_dir=cache_dir(args.cache_dir))
    collected: list[dict[str, Any]] = []
    total_results = 0
    total_pages = 1

    try:
        page = args.pages.first
        while args.pages.contains(page):
            result = await client.search(
                query=args.query,
                page=page,
                from_year=args.from_year,
                to_year=args.to_year,
                title=args.title,
                place=args.place,
                language=args.language,
                subject=args.subject,
                sort=args.sort,
            )

            total_results = result["total_results"]
            total_pages = result["total_pages"]
            documents = result["documents"]

            if page > total_pages:
                break

            if args.json:
                collected.extend(documents)
            else:
                label = args.query or "(filters only)"
                print(f"# {label} — {total_results} results, page {page} of {total_pages}")
                if not documents:
                    print("  (no documents on this page)")
                for offset, document in enumerate(documents):
                    position = (page - 1) * RESULTS_PER_PAGE + offset + 1
                    print(format_document(position, document))
                print()

            if page >= total_pages:
                break
            page += 1
    finally:
        await client.close()

    if args.json:
        json.dump(
            {
                "query": args.query,
                "total_results": total_results,
                "total_pages": total_pages,
                "pages_fetched": str(args.pages),
                "documents": collected,
            },
            sys.stdout,
            indent=2,
            ensure_ascii=False,
        )
        print()

    return 0


async def run_snippets(args: argparse.Namespace) -> int:
    """Show which pages of one issue a query appears on."""
    client = AnnoClient(cache_dir=cache_dir(args.cache_dir))

    try:
        snippets = await client.get_snippets(
            document_id=args.identifier, query=args.query
        )
    finally:
        await client.close()

    if args.json:
        json.dump(
            {"identifier": args.identifier, "query": args.query, "snippets": snippets},
            sys.stdout,
            indent=2,
            ensure_ascii=False,
        )
        print()
        return 0

    if not snippets:
        print(f"# {args.identifier} — no occurrences of {args.query}")
        return 0

    print(f"# {args.identifier} — {len(snippets)} occurrence(s) of {args.query}")
    for snippet in snippets:
        page = snippet.get("page")
        print(f"    Seite {page if page is not None else '?'}  · {snippet.get('text', '')}")
        if url := snippet.get("url"):
            print(f"        {url}")

    return 0


async def run_get(args: argparse.Namespace) -> int:
    """Download an issue's OCR text and print the path to the cached file."""
    client = AnnoClient(cache_dir=cache_dir(args.cache_dir))

    try:
        path = await client.download_text(
            document_id=args.identifier, page=args.page, refresh=args.refresh
        )
    finally:
        await client.close()

    print(path)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM_NAME,
        description=(
            "Search ANNO (AustriaN Newspapers Online), the historical newspaper "
            "archive of the Österreichische Nationalbibliothek."
        ),
    )
    parser.add_argument(
        "--cache-dir",
        default=None,
        help="override the download cache location (default: $XDG_CACHE_HOME/anno-mcp)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    search = subparsers.add_parser(
        "search",
        help="search full text, with optional filters",
        description=(
            "Search ANNO's OCR text. Bare words are ANDed; AND, OR and NOT must be "
            "UPPERCASE; \"quoted phrases\" match exactly and a trailing * is a "
            "wildcard. Results resolve to issues, not pages - follow up with "
            "'anno snippets' to find the page. The collection is German-language "
            "Austrian press, so search in German."
        ),
    )
    search.add_argument("query", nargs="?", default="", help="search query (optional if filtering)")
    search.add_argument(
        "--pages",
        type=parse_page_range,
        default=PageRange(1, 1),
        metavar="SPEC",
        help="which result pages to fetch: N, N-M, or 'all' (default: 1)",
    )
    search.add_argument("--from-year", type=int, metavar="YEAR", help="earliest year, inclusive")
    search.add_argument("--to-year", type=int, metavar="YEAR", help="latest year, inclusive")
    search.add_argument(
        "--title",
        metavar="ACRONYM",
        help="restrict to one title by its acronym, e.g. nwg (Neues Wiener Tagblatt)",
    )
    search.add_argument("--place", metavar="PLACE", help="place of publication, e.g. Wien")
    search.add_argument("--language", metavar="CODE", help="language code: ger, hun, cze, slo")
    search.add_argument("--subject", metavar="TEXT", help="subject/theme, e.g. Tageszeitung")
    search.add_argument(
        "--sort",
        choices=SORT_ORDERS,
        default=DEFAULT_SORT,
        help=(
            "result ordering (default: relevance). ANNO's totals are true match "
            "counts, so date order is safe to use on any query you intend to sweep"
        ),
    )
    search.add_argument("--json", action="store_true", help="emit JSON instead of text")
    search.set_defaults(handler=run_search)

    snippets = subparsers.add_parser(
        "snippets",
        help="locate a query inside one issue, page by page",
        description=(
            "Show which pages of one issue a query appears on, with the matched "
            "terms in {braces} and a citation URL for each page. This is the cheap "
            "way to judge a search result, and often the whole deliverable."
        ),
    )
    snippets.add_argument("identifier", help="document id, e.g. ANNO_dmo19330626")
    snippets.add_argument("query", help="terms to locate within the issue")
    snippets.add_argument("--json", action="store_true", help="emit JSON instead of text")
    snippets.set_defaults(handler=run_snippets)

    get = subparsers.add_parser(
        "get",
        help="download an issue's OCR text, printing the cache path",
        description=(
            "Download OCR plain text and print the path to the cached file. ANNO "
            "serves text one page at a time, so a whole issue costs one request "
            "per page - use --page when you already know which page you want."
        ),
    )
    get.add_argument("identifier", help="document id, e.g. ANNO_dmo19330626")
    get.add_argument(
        "--page",
        type=int,
        default=None,
        metavar="N",
        help="fetch a single page instead of the whole issue (far cheaper)",
    )
    get.add_argument(
        "--refresh",
        action="store_true",
        help="re-download even if a cached copy exists",
    )
    get.set_defaults(handler=run_get)

    return parser


def main() -> None:
    args = build_parser().parse_args()

    try:
        exit_code = asyncio.run(args.handler(args))
    except KeyboardInterrupt:
        exit_code = 130
    except (RuntimeError, ValueError) as error:
        print(f"{PROGRAM_NAME}: {error}", file=sys.stderr)
        exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
