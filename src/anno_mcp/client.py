"""ANNO API client with search, page-level snippets and OCR text download.

ANNO publishes no API. What this client talks to is the REST backend of the
AnnoSearch single-page app at https://anno.onb.ac.at/anno-suche, discovered by
reading its JavaScript bundle, plus the long-standing `annoshow` CGI that the
page viewer's "Text" button opens. Both are unauthenticated and answer JSON and
plain text respectively, so this is a real API in everything but documentation -
with the one caveat that nobody has promised to keep it stable. See
`_raise_for_html_shell` for how drift is detected.
"""

from __future__ import annotations

import asyncio
import re
from html import unescape
from pathlib import Path
from typing import Any

import httpx

from .paths import cache_dir as default_cache_dir
from .ratelimit import CrossProcessRateLimiter, configured_interval

USER_AGENT = "anno-mcp/0.1.0 (historical research tool)"

# Result ordering. The names match the other archive clients; the values are
# what ANNO's `sort` parameter expects. Relevance is ANNO's own default,
# expressed by omitting `sort` entirely rather than by naming a relevance key.
SORT_VALUES = {
    "relevance": "",
    "date_asc": "date asc",
    "date_desc": "date desc",
}
SORT_ORDERS = tuple(SORT_VALUES)
DEFAULT_SORT = "relevance"

# ANNO fixes the result page size server-side and exposes no parameter for it.
# Ten is what it returns; the first page returns nine because hit numbering is
# 1-based while `from` is 0-based, so hit 0 does not exist. Nothing is skipped.
RESULTS_PER_PAGE = 10

# A document id is the owner prefix, the title acronym, then an eight-digit
# reference: YYYYMMDD for newspapers, YYYY+item number for periodicals.
DOCUMENT_ID_PATTERN = re.compile(r"^(ANNOP?)_(.+?)(\d{8})$")

# Every page of OCR text arrives under a header line the CGI prepends,
# e.g. "[ 2023-06-29 10:47:55.708 - 19330626 - Seite 7 ]". A page that does not
# exist returns that header and nothing else, with HTTP 200.
OCR_HEADER_PATTERN = re.compile(r"^\s*\[\s*[\d.\- :]+-\s*Seite\s+\d+\s*\]\s*", re.IGNORECASE)

# How many consecutive empty pages end a whole-issue download. ANNO answers any
# page past the end with an empty body rather than an error, and genuinely blank
# plates do occur mid-issue, so a single empty page is not proof of the end.
EMPTY_PAGE_RUN_TO_STOP = 3

# A guard against a runaway scan if the empty-page heuristic ever fails. The
# largest issue seen while writing this client ran to 288 pages.
MAX_ISSUE_PAGES = 600


class AnnoClient:
    """Client for interacting with the ANNO (Austrian Newspapers Online) API."""

    SEARCH_BASE_URL = "https://anno.onb.ac.at/anno-suche/rest"
    OCR_URL = "https://anno.onb.ac.at/cgi-content/annoshow"
    VIEWER_BASE_URL = "http://data.onb.ac.at"

    def __init__(
        self,
        cache_dir: Path | None = None,
        max_concurrent_requests: int = 1,
        min_request_interval: float | None = None,
    ):
        """Initialize the ANNO client.

        Args:
            cache_dir: Directory for caching downloaded text files
            max_concurrent_requests: Maximum number of concurrent API requests
            min_request_interval: Minimum delay (seconds) between requests;
                defaults to the configured interval
        """
        self.cache_dir = Path(cache_dir) if cache_dir is not None else default_cache_dir()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.client = httpx.AsyncClient(
            timeout=60.0,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/plain"},
        )
        self._request_semaphore = asyncio.Semaphore(max_concurrent_requests)
        # Spacing is shared with every other process using this cache: an
        # instance attribute paces nothing once each CLI call is its own process.
        self._rate_limiter = CrossProcessRateLimiter(
            state_file=self.cache_dir / ".rate-limit",
            min_interval=(
                min_request_interval
                if min_request_interval is not None
                else configured_interval()
            ),
        )

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()

    # ---------------------------------------------------------------- search

    async def search(
        self,
        query: str,
        page: int = 1,
        from_year: int | None = None,
        to_year: int | None = None,
        title: str | None = None,
        place: str | None = None,
        language: str | None = None,
        subject: str | None = None,
        sort: str = DEFAULT_SORT,
    ) -> dict[str, Any]:
        """Search ANNO's full text.

        Everything goes through `/search/complex`, including unfiltered queries:
        it accepts the same query syntax as `/search/simple` and returns the same
        totals (both report 1385 for `Hanussen`), so one code path avoids any
        chance of the two endpoints drifting apart in meaning.

        Args:
            query: Search terms. Bare words are ANDed; AND/OR/NOT, "quoted
                phrases" and trailing `*` wildcards all work.
            page: Page number (1-indexed)
            from_year: Earliest year, inclusive
            to_year: Latest year, inclusive
            title: Title acronym to restrict to, e.g. `nwg`. This is a strict
                facet filter, not the loose `title=` text field - see
                `_build_search_params`.
            place: Place of publication, e.g. `Wien`
            language: Language code, e.g. `ger`
            subject: Subject/theme, e.g. `Tageszeitung`
            sort: Result ordering, one of SORT_ORDERS (default relevance)

        Returns:
            Dictionary containing:
                - page: Current page number
                - total_results: True count of matching issues
                - total_pages: Number of result pages
                - documents: List of issue metadata
        """
        if sort not in SORT_VALUES:
            raise ValueError(
                f"Unknown sort order {sort!r}; expected one of {', '.join(SORT_ORDERS)}"
            )
        if page < 1:
            raise ValueError(f"Page numbers start at 1; got {page}")

        params = self._build_search_params(
            query=query,
            page=page,
            from_year=from_year,
            to_year=to_year,
            title=title,
            place=place,
            language=language,
            subject=subject,
            sort=sort,
        )

        payload = await self._get_json(f"{self.SEARCH_BASE_URL}/search/complex", params)

        if "totalHits" not in payload:
            raise RuntimeError(
                "ANNO search response carried no totalHits field; the endpoint's "
                f"shape may have changed. Keys present: {sorted(payload)}"
            )

        total_results = int(payload["totalHits"])
        documents = [
            self._parse_document(record) for record in payload.get("documents") or []
        ]

        # An empty result set is one empty page, not zero pages, so that callers
        # looping over pages behave the same here as for any other source.
        total_pages = max(
            1, (total_results + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE
        )

        return {
            "page": page,
            "total_results": total_results,
            "total_pages": total_pages,
            "documents": documents,
        }

    def _build_search_params(
        self,
        query: str,
        page: int,
        from_year: int | None,
        to_year: int | None,
        title: str | None,
        place: str | None,
        language: str | None,
        subject: str | None,
        sort: str,
    ) -> list[tuple[str, str]]:
        """Assemble the query string for `/search/complex`.

        Returned as a list of pairs rather than a dict because `selectedFilters`
        repeats, once per facet constraint.

        Title and place go through `selectedFilters` rather than through the
        endpoint's own `title=` and `place=` fields. Those fields are not
        filters: ANNO's own help states that choosing a title "does not
        automatically search only in that title - instead the filter's text is
        used", i.e. the value is folded into the free-text query. Searching
        `Hanussen` restricted to `nwg` returns 97 issues through
        `selectedFilters` and something quite different through `title=`.
        """
        params: list[tuple[str, str]] = []

        if query and query.strip():
            params.append(("text", query.strip()))

        # ANNO accepts a bare year on both bounds as well as a full date.
        if from_year is not None:
            params.append(("dateFrom", str(from_year)))
        if to_year is not None:
            params.append(("dateTo", str(to_year)))

        if language:
            params.append(("language", language.strip()))
        if subject:
            params.append(("subject", subject.strip()))

        for facet_type, value in (("title", title), ("place", place)):
            if value:
                params.append(("selectedFilters", f"{facet_type}:{value.strip()}"))

        if sort_value := SORT_VALUES[sort]:
            params.append(("sort", sort_value))

        params.append(("from", str((page - 1) * RESULTS_PER_PAGE)))
        params.append(("facets", "true"))
        return params

    def _parse_document(self, record: dict[str, Any]) -> dict[str, Any]:
        """Parse one search result into issue metadata.

        Raises rather than returning None on a record it cannot read. Dropping it
        would shrink the result list while the reported total still counted it,
        so a search would silently under-report; for a tool whose value rests on
        exhaustivity a loud failure beats a quiet omission.
        """
        document_id = record.get("docId")
        if not document_id:
            raise RuntimeError(
                f"ANNO search result carried no docId: {record!r}"
            )

        uid = record.get("uid")
        if not isinstance(uid, dict):
            raise RuntimeError(
                f"ANNO search result {document_id} carried no uid object: {record!r}"
            )

        owner = uid.get("owner")
        if owner == "ANNO":
            # Newspapers: a real calendar date.
            anno_date = uid.get("annoDate")
            if not isinstance(anno_date, dict) or not anno_date.get("date"):
                raise RuntimeError(
                    f"ANNO newspaper record {document_id} carried no annoDate.date: {record!r}"
                )
            date = str(anno_date["date"])
            year = int(date[:4])
        elif owner == "ANNOP":
            # Periodicals: a year and an item number, with no calendar date at
            # all. Code that assumes `annoDate` crashes here, which is exactly
            # how this shape was found.
            if uid.get("year") is None:
                raise RuntimeError(
                    f"ANNO periodical record {document_id} carried no year: {record!r}"
                )
            date = None
            year = int(uid["year"])
        else:
            # A third owner would mean ANNO has grown a document class this
            # client has never seen. Guessing at its shape is how silent data
            # loss starts.
            raise RuntimeError(
                f"ANNO record {document_id} has unknown owner {owner!r}; expected "
                f"'ANNO' (newspaper) or 'ANNOP' (periodical). Record: {record!r}"
            )

        page_count = record.get("pageCount")
        hits_in_document = record.get("totalHitsInDoc")

        return {
            "identifier": document_id,
            "title": record.get("displayTitle") or "Untitled",
            "date": date,
            "year": year,
            "type": record.get("type"),
            "is_periodical": owner == "ANNOP",
            "places": record.get("places") or [],
            "languages": record.get("languages") or [],
            "page_count": int(page_count) if page_count is not None else None,
            "hits_in_document": (
                int(hits_in_document) if hits_in_document is not None else None
            ),
            "url": record.get("openUrl"),
        }

    # -------------------------------------------------------------- snippets

    async def get_snippets(self, document_id: str, query: str) -> list[dict[str, Any]]:
        """Fetch page-level KWIC snippets for one issue.

        This is the cheap triage step, and the reason ANNO is worth using: a hit
        resolves to a page of an issue with the matched terms in context, so a
        false positive can be rejected without downloading anything.

        Args:
            document_id: Issue identifier, e.g. `ANNO_dmo19330626`
            query: Terms to locate within the issue

        Returns:
            List of dictionaries containing:
                - page: Page number the occurrence sits on
                - page_label: Page label as printed, which may differ
                - text: Snippet with matched terms marked in {braces}
                - url: Stable citation URL for that page
                - image_url: IIIF crop of the matched region, or None
        """
        params = [("documentId", document_id.strip()), ("query", query.strip())]
        payload = await self._get_json(f"{self.SEARCH_BASE_URL}/search/snippet", params)

        snippets: list[dict[str, Any]] = []
        for page_entry in payload.get("snippetPages") or []:
            for snippet in page_entry.get("snippets") or []:
                snippets.append(
                    {
                        "page": snippet.get("page", page_entry.get("page")),
                        "page_label": snippet.get(
                            "pageLabel", page_entry.get("pageLabel")
                        ),
                        "text": self._clean_snippet(snippet.get("text") or ""),
                        "url": snippet.get("openURL") or page_entry.get("openURL"),
                        "image_url": snippet.get("imageURL"),
                    }
                )
        return snippets

    @staticmethod
    def _clean_snippet(raw: str) -> str:
        """Turn a snippet payload into readable text with matches in braces.

        ANNO marks each match with `<span class="snp_txt_hl">` and breaks lines
        with `<br/>`, then HTML-escapes the German characters around them
        (`&auml;`, `&szlig;`). The span becomes `{braces}` because knowing which
        token actually matched is how a reader spots a substring false positive -
        and on Fraktur OCR that matters more than usual.

        Unescaping happens last. The markup arrives literal rather than escaped,
        so unescaping first would be harmless here but would break the moment
        ANNO started escaping it.

        Soft hyphens are dropped for the same reason they are dropped from
        downloaded text: a word broken across a line arrives as `Ha\xad` + `<br/>`
        + `nussen`, and the invisible character makes the snippet read as though
        it held a stray space. Dropping it leaves `{Ha} {nussen?"}`, which is an
        honest rendering — the term matched, in two pieces, across a line break.
        """
        text = re.sub(
            r"<span[^>]*class=['\"]?snp_txt_hl['\"]?[^>]*>(.*?)</span>",
            r"{\1}",
            raw,
            flags=re.DOTALL | re.IGNORECASE,
        )
        text = re.sub(r"(?i)<\s*br\s*/?>", " ", text)
        text = re.sub(r"<[^>]+>", "", text)
        text = unescape(text)
        text = text.replace("­", "")
        return " ".join(text.split())

    # ------------------------------------------------------------- full text

    async def download_text(
        self,
        document_id: str,
        page: int | None = None,
        refresh: bool = False,
    ) -> str:
        """Download OCR plain text for an issue, or for one page of it.

        Args:
            document_id: Issue identifier, e.g. `ANNO_dmo19330626`
            page: Single page to fetch; None fetches the whole issue
            refresh: Ignore any cached copy and fetch again

        Returns:
            Path to the cached text file
        """
        owner, acronym, reference = self.parse_document_id(document_id)

        if owner == "ANNOP":
            # The periodical viewer (`anno-plus`) has no "Text" button, and the
            # CGI answers a periodical reference with a Perl `substr outside of
            # string` crash. Periodicals are searchable and have snippets; their
            # OCR simply is not exposed. Saying so plainly beats a 500.
            raise RuntimeError(
                f"{document_id} is a periodical (ANNOP), and ANNO does not expose "
                "OCR text for periodicals - only newspapers (ANNO_) have a text "
                "endpoint. Use `anno snippets` instead: snippets do work for "
                "periodicals and carry page numbers and citation URLs."
            )

        suffix = f"_p{page}" if page is not None else ""
        cache_file = self.cache_dir / f"{document_id}{suffix}.txt"
        if cache_file.exists() and not refresh:
            return str(cache_file.resolve())

        if page is not None:
            body = await self._fetch_page_text(acronym, reference, page)
            if not body:
                raise RuntimeError(
                    f"ANNO returned no OCR text for {document_id} page {page}. "
                    "Nothing has been cached; the page may be beyond the end of "
                    "the issue, or image-only."
                )
            sections = [self._format_page(document_id, page, body)]
        else:
            sections = await self._fetch_issue_text(document_id, acronym, reference)

        cache_file.write_text("\n\n".join(sections) + "\n", encoding="utf-8")
        return str(cache_file.resolve())

    async def _fetch_issue_text(
        self, document_id: str, acronym: str, reference: str
    ) -> list[str]:
        """Fetch every page of an issue, in order, and format them.

        A whole-issue fetch is not available: `annoshow` answers a bare
        `acronym|reference` with HTTP 400, and a page range with HTTP 400 too, so
        the pages have to be walked one request at a time. At the default pacing
        a sixteen-page issue therefore costs the better part of a minute, and a
        hundred-page one costs five - which is why `--page` exists.

        There is no page-count field to walk against, so the end of the issue is
        found by walking into it: ANNO answers any page past the end with HTTP
        200 and a header but no body. A single empty page is not proof of the
        end, because blank plates occur mid-issue, so the walk stops only after a
        run of them and trailing empties are discarded.
        """
        sections: list[str] = []
        pending: list[str] = []
        empty_run = 0
        page = 1

        while page <= MAX_ISSUE_PAGES:
            body = await self._fetch_page_text(acronym, reference, page)

            if body:
                # Blank pages inside the issue are kept, so page numbering in
                # the file matches page numbering in the issue.
                sections.extend(pending)
                pending = []
                empty_run = 0
                sections.append(self._format_page(document_id, page, body))
            else:
                empty_run += 1
                if empty_run >= EMPTY_PAGE_RUN_TO_STOP:
                    break
                pending.append(self._format_page(document_id, page, ""))

            page += 1

        if not sections:
            raise RuntimeError(
                f"ANNO returned no OCR text for any page of {document_id}. Nothing "
                "has been cached; the issue may not be full-text indexed - roughly "
                "9% of ANNO's holdings are not."
            )
        return sections

    async def _fetch_page_text(self, acronym: str, reference: str, page: int) -> str:
        """Fetch and clean one page of OCR text. Empty string means no content."""
        params = [("text", f"{acronym}|{reference}|{page}")]
        response = await self._rate_limited_get(self.OCR_URL, params=params)

        if response.status_code == 429:
            raise RuntimeError(
                "Rate limited by ANNO (HTTP 429). Stop querying and wait before "
                "retrying; consider raising ANNO_MIN_REQUEST_INTERVAL."
            )
        # The CGI reports a reference it cannot parse as a Perl crash carrying
        # HTTP 500, which is otherwise indistinguishable from a server fault.
        if response.status_code == 500 and "Software error" in response.text:
            raise RuntimeError(
                f"ANNO's text CGI could not handle reference {acronym}|{reference}"
                f"|{page} (Perl 'Software error'). This is what a periodical "
                "reference produces; newspapers use an eight-digit YYYYMMDD."
            )
        response.raise_for_status()

        return self._clean_ocr_text(response.text)

    @staticmethod
    def _clean_ocr_text(raw: str) -> str:
        """Strip the CGI's header line and normalise the page's text.

        Hyphenation is undone here rather than left in place. ANNO's OCR marks a
        word broken across a line with U+00AD immediately before the newline, so
        the raw text holds `voll\xad\nständig` and `Hanas\xad\nsen`; the search
        index joins those back up, but a local grep over a downloaded file would
        not, and would miss the very occurrences the search found.

        Deleting the soft hyphen alone is not enough — it leaves `voll\nständig`,
        which still does not match `vollständig`. The line break has to go with
        it, which is why this is a join rather than a strip.

        Ordinary hyphens at a line end are left alone. They are ambiguous in a
        way soft hyphens are not: `Hoch-Räthseln` is a real compound and joining
        it would corrupt the word.
        """
        text = OCR_HEADER_PATTERN.sub("", raw, count=1)
        text = text.replace("\r", "")
        text = re.sub(r"­[ \t]*\n[ \t]*", "", text)
        # Any soft hyphen not sitting at a line break is simply invisible noise.
        text = text.replace("­", "")
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _format_page(document_id: str, page: int, body: str) -> str:
        """Render one page with a marker a reader or a grep can navigate by."""
        header = f"=== {document_id} Seite {page} ==="
        return f"{header}\n{body}" if body else f"{header}\n[no OCR text]"

    # ------------------------------------------------------------- citations

    def citation_url(self, document_id: str, page: int | None = None) -> str:
        """Build the stable public URL a human can open to check a quote."""
        owner, acronym, reference = self.parse_document_id(document_id)
        url = f"{self.VIEWER_BASE_URL}/{owner}/{acronym}{reference}"
        if page is not None:
            url += f"?seite={page}"
        return url

    @staticmethod
    def parse_document_id(document_id: str) -> tuple[str, str, str]:
        """Split a document id into owner, title acronym and eight-digit reference.

        `ANNO_dmo19330626` -> `('ANNO', 'dmo', '19330626')`, a newspaper issue
        of 26 June 1933. `ANNOP_klr19180004` -> `('ANNOP', 'klr', '19180004')`,
        item 4 of the 1918 volume of a periodical. The reference is matched from
        the right, because a title acronym may itself contain digits.
        """
        match = DOCUMENT_ID_PATTERN.match(document_id.strip())
        if not match:
            raise ValueError(
                f"Unrecognised ANNO document id {document_id!r}; expected something "
                "like ANNO_dmo19330626 or ANNOP_klr19180004"
            )
        owner, acronym, reference = match.groups()
        return owner, acronym, reference

    # ----------------------------------------------------------------- HTTP

    async def _get_json(
        self, url: str, params: list[tuple[str, str]]
    ) -> dict[str, Any]:
        """GET a JSON endpoint, refusing anything that is not really JSON."""
        response = await self._rate_limited_get(url, params=params)

        if response.status_code == 429:
            raise RuntimeError(
                "Rate limited by ANNO (HTTP 429). Stop querying and wait before "
                "retrying; consider raising ANNO_MIN_REQUEST_INTERVAL."
            )
        response.raise_for_status()

        self._raise_for_html_shell(response, url)

        try:
            payload = response.json()
        except ValueError as error:
            raise RuntimeError(
                f"ANNO returned a non-JSON body from {url}: {response.text[:200]!r}"
            ) from error

        if not isinstance(payload, dict):
            raise RuntimeError(
                f"ANNO returned {type(payload).__name__}, expected an object, from {url}"
            )
        return payload

    @staticmethod
    def _raise_for_html_shell(response: httpx.Response, url: str) -> None:
        """Reject an HTTP 200 that carries the search app instead of data.

        The REST endpoints are the private backend of an Angular single-page app.
        If a path stops existing, the server does not answer 404 - it serves the
        app's own HTML shell with HTTP 200, which would otherwise surface as an
        unhelpful JSON decode error several layers away from the cause.
        """
        head = response.text[:1000].lstrip().lower()
        if head.startswith("<!doctype html") or head.startswith("<html"):
            raise RuntimeError(
                f"ANNO served its HTML search page instead of JSON for {url}.\n"
                "\n"
                "This is almost certainly endpoint drift, which is a bug in this "
                "tool rather than a problem with your query or a transient "
                "failure. /anno-suche/rest is the undocumented backend of the "
                "AnnoSearch single-page app: when the app is redeployed its paths "
                "can move, and the server answers a path that no longer exists by "
                "serving the app's HTML shell with HTTP 200 instead of a 404.\n"
                "\n"
                "Retrying will not help, and neither will rewording the search. "
                "If you are an agent that hit this mid-research:\n"
                "  1. Stop querying ANNO and tell the user what happened — the "
                "source is unavailable until the client is fixed, so any report "
                "you write must say ANNO was not searched.\n"
                "  2. Re-derive the endpoints: fetch https://anno.onb.ac.at/anno-suche, "
                "find the hashed bundle it loads (main-<HASH>.js), and search it "
                "for `apiUrl` and the /search/ paths near it.\n"
                "  3. Fix SEARCH_BASE_URL (and the /search/complex, /search/snippet "
                "paths that hang off it) in this client's client.py, verify with "
                "one live search, and commit the fix to the anno-mcp repository so "
                "the next session does not rediscover it.\n"
                "\n"
                "This message is the drift signal described in anno-mcp's "
                "CLAUDE.md; there is no other symptom to look for."
            )

    async def _rate_limited_get(self, url: str, **kwargs: Any) -> httpx.Response:
        """Issue a GET request honoring concurrency and rate limits."""
        async with self._request_semaphore:
            await self._rate_limiter.acquire()
            return await self.client.get(url, **kwargs)
