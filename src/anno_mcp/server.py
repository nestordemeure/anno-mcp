"""ANNO MCP Server - FastMCP tools for searching Austrian historical newspapers."""

import argparse
import sys

from mcp import Resource
from mcp.server.fastmcp import FastMCP

# Handle both direct execution and package import
try:
    from .client import DEFAULT_SORT, AnnoClient
    from .paths import cache_dir
except ImportError:
    from anno_mcp.client import DEFAULT_SORT, AnnoClient
    from anno_mcp.paths import cache_dir

# Parse command-line arguments
parser = argparse.ArgumentParser(description="ANNO MCP Server")
parser.add_argument(
    "--enable-advanced-search",
    action="store_true",
    help="Enable the advanced_search_anno tool with filter parameters",
)
# Parse known args to allow FastMCP to handle its own args
args, unknown = parser.parse_known_args()
# Put unknown args back for FastMCP
sys.argv = [sys.argv[0]] + unknown

mcp = FastMCP("ANNO")

ENABLE_ADVANCED_SEARCH = args.enable_advanced_search

_client: AnnoClient | None = None


def get_client() -> AnnoClient:
    """Get or create the global ANNO client."""
    global _client
    if _client is None:
        _client = AnnoClient(cache_dir=cache_dir())
    return _client


@mcp.tool()
async def search_anno(query: str, page: int = 1, sort: str = DEFAULT_SORT) -> dict:
    """Search ANNO, the Austrian National Library's historical newspaper archive.

    Covers roughly 28 million pages from over 1,600 Austrian newspaper and
    magazine titles, 1735 to the present, overwhelmingly German-language. Over
    91% of holdings are full-text searchable.

    Results resolve to an ISSUE, not a page. Use get_snippets with a returned
    identifier to find which page a term appears on.

    Args:
        query: Text to search in OCR content.
            - Bare words are ANDed: "Hanussen Hellseher" needs both
            - Exact phrases: '"Erik Jan Hanussen"'
            - AND / OR / NOT, which MUST BE UPPERCASE
            - Trailing wildcard: "Hanuss*"
        page: Page number for pagination, 1-indexed (default: 1). ANNO fixes the
            page size at 10 results and offers no way to raise it.
        sort: Result ordering — "relevance" (default), "date_asc" or "date_desc".
            ANNO's totals are true match counts rather than a relevance tail, so
            date ordering is safe on any query you mean to sweep.

    Returns:
        Dictionary containing:
            - page: Current page number
            - total_results: True count of matching issues
            - total_pages: Total number of pages available
            - documents: List of issues with:
                - identifier: Document id, e.g. ANNO_dmo19330626
                - title: Issue title with its date
                - date: ISO date for newspapers, None for periodicals
                - year: Year of publication
                - type: Zeitung (newspaper) or Zeitschrift (periodical)
                - is_periodical: True when OCR download is unavailable
                - places, languages: Publication place and language
                - page_count: Pages in the issue
                - hits_in_document: Occurrences of the query in the issue
                - url: Stable citation URL

    Examples:
        search_anno(query="Hanussen")
        search_anno(query='"Erik Jan Hanussen"')
        search_anno(query="Hellseher OR Gedankenleser")
        search_anno(query="Hanuss*")
    """
    client = get_client()
    return await client.search(query=query, page=page, sort=sort)


if ENABLE_ADVANCED_SEARCH:

    @mcp.tool()
    async def advanced_search_anno(
        query: str = "",
        page: int = 1,
        from_year: int | None = None,
        to_year: int | None = None,
        title: str | None = None,
        place: str | None = None,
        language: str | None = None,
        subject: str | None = None,
        medium: str | None = None,
        sort: str = DEFAULT_SORT,
    ) -> dict:
        """Search ANNO with filters for date, title, place, language, subject and medium.

        Args:
            query: Same syntax as search_anno. Empty string filters only.
            page: Page number, 1-indexed (default: 1)
            from_year: Earliest year, inclusive. Example: 1880
            to_year: Latest year, inclusive. Example: 1935
            title: Title acronym to restrict to, e.g. "nwg" for Neues Wiener
                Tagblatt. This is a strict filter on the title facet.
            place: Place of publication, copied verbatim from the facet, e.g.
                "Wien", "Graz", "Praha (Prag)". A near-miss such as "Prag"
                silently selects a different, nearly empty place.
            language: Language code, e.g. "ger", "hun", "cze", "slo", "ita"
            subject: Subject/theme, e.g. "Tageszeitung", "Exilpresse". Publication
                frequency lives here too: "Tageszeitung", "Wochenzeitung".
            medium: Material type: "newspaper" (ANNO's own value is "journal")
                for Zeitungen, whose OCR text download_text can fetch, or
                "periodical" for Zeitschriften, which have snippets only. The two
                partition the results exactly. ANNO's German labels "Zeitung" and
                "Zeitschrift" are rejected rather than silently returning zero.
            sort: "relevance" (default), "date_asc" or "date_desc"

        Returns:
            The same structure as search_anno.

        Examples:
            advanced_search_anno(query="Cumberland Gedankenleser", from_year=1884, to_year=1888)
            advanced_search_anno(query="Hanussen", title="nwg")
            advanced_search_anno(query="Hellseher", place="Wien", from_year=1920, to_year=1933)
            advanced_search_anno(query="Hanussen", medium="periodical")
        """
        client = get_client()
        return await client.search(
            query=query,
            page=page,
            from_year=from_year,
            to_year=to_year,
            title=title,
            place=place,
            language=language,
            subject=subject,
            medium=medium,
            sort=sort,
        )


@mcp.tool()
async def get_snippets(identifier: str, query: str) -> dict:
    """Find which pages of one ANNO issue a query appears on, with context.

    This is the cheap triage step and the reason ANNO is worth using: a hit
    resolves to a page with the matched terms in context, so a false positive can
    be rejected without downloading anything. It also works for periodicals,
    whose OCR text cannot be downloaded at all.

    Args:
        identifier: Document id from a search result, e.g. "ANNO_dmo19330626"
        query: Terms to locate within the issue

    Returns:
        Dictionary containing:
            - identifier: The document id
            - query: The query used
            - snippets: List of occurrences with:
                - page: Page number the occurrence sits on
                - page_label: Page label as printed
                - text: Snippet with matched terms in {braces}
                - url: Stable citation URL for that exact page
                - image_url: IIIF crop of the matched region

    Note:
        ANNO returns at most 10 snippets per issue however many hits it reports,
        so a heavily-covered issue shows a sample rather than every occurrence.

    Examples:
        get_snippets("ANNO_dmo19330626", "Hanussen")
        get_snippets("ANNO_wsb18840309", "Cumberland")
    """
    client = get_client()
    snippets = await client.get_snippets(document_id=identifier, query=query)
    return {"identifier": identifier, "query": query, "snippets": snippets}


@mcp.tool()
async def download_text(identifier: str, page: int | None = None) -> str:
    """Download OCR plain text for an ANNO newspaper issue and cache it locally.

    Args:
        identifier: Document id, e.g. "ANNO_dmo19330626"
        page: Single page to fetch. Omit for the whole issue.

    Returns:
        Path to the cached text file (as string)

    IMPORTANT:
        ANNO serves text one page at a time, so a whole issue costs one request
        per page — a 104-page issue is 104 paced requests. Pass `page` whenever
        get_snippets has already told you which page you want.

        Periodicals (identifiers starting ANNOP_) have no text endpoint at all
        and will raise. Use get_snippets for those.

    Example:
        path = download_text("ANNO_dmo19330626", page=7)
    """
    client = get_client()
    return await client.download_text(document_id=identifier, page=page)


@mcp.resource("anno://info")
async def server_info() -> Resource:
    """Provide information about the ANNO MCP server."""
    return Resource(
        uri="anno://info",
        name="ANNO MCP Server Info",
        mimeType="text/plain",
        text="""ANNO MCP Server

Provides access to ANNO (AustriaN Newspapers Online), the historical newspaper
archive of the Österreichische Nationalbibliothek: ~28 million pages from 1,600+
mostly German-language Austrian titles, 1735 onwards, 91%+ full-text searchable.

Available Tools:
- search_anno(query, page, sort): Search OCR text; results resolve to issues
- get_snippets(identifier, query): Page-level KWIC with citation URLs
- download_text(identifier, page): OCR plain text, cached locally
- advanced_search_anno(...): Search with date, title, place, language, subject
  and medium (newspaper vs periodical) filters

Query Syntax:
- Bare words are ANDed; AND, OR, NOT must be UPPERCASE
- Exact phrases: '"Erik Jan Hanussen"'
- Trailing wildcard: "Hanuss*"

Result totals are true match counts, not a relevance tail.
""",
    )


def main():
    """Run the ANNO MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
