from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup, Tag

from app.core.config import Settings, get_settings

CALENDAR_URL = "https://corporate.bwfbadminton.com/events/calendar/"
CALENDAR_HOST = "corporate.bwfbadminton.com"
DRAW_DOCUMENT_HOST = "extranet.bwf.sport"
DRAW_DOCUMENT_PREFIX = "/docs/events/"
DRAW_LABEL_PATTERN = re.compile(r"\bdraws?(?:\s|-|_)*", re.IGNORECASE)
DATE_RANGE_PATTERN = re.compile(
    r"(?P<start_day>\d{1,2})(?:\s+(?P<start_month>[A-Z]+))?\s*-\s*(?P<end_day>\d{1,2})\s+(?P<end_month>[A-Z]+)",
    re.IGNORECASE,
)
MONTHS = {
    "JANUARY": 1,
    "FEBRUARY": 2,
    "MARCH": 3,
    "APRIL": 4,
    "MAY": 5,
    "JUNE": 6,
    "JULY": 7,
    "AUGUST": 8,
    "SEPTEMBER": 9,
    "OCTOBER": 10,
    "NOVEMBER": 11,
    "DECEMBER": 12,
}


@dataclass(frozen=True)
class CorporateCalendarResponse:
    url: str
    status_code: int
    retrieved_at: datetime
    content: bytes
    content_hash: str
    content_type: str | None


@dataclass(frozen=True)
class CorporateDocumentResponse:
    url: str
    status_code: int
    retrieved_at: datetime
    content: bytes
    content_hash: str
    content_type: str | None


@dataclass(frozen=True)
class CalendarDocumentLink:
    label: str
    url: str


@dataclass(frozen=True)
class CorporateCalendarEntry:
    source_tournament_id: str
    name: str
    country_code: str | None
    start_date: date | None
    end_date: date | None
    category: str | None
    city: str | None
    source_url: str | None
    draw_date_text: str | None
    draw_documents: tuple[CalendarDocumentLink, ...]
    raw_row: dict[str, str | None]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def normalize_text(value: str) -> str:
    return " ".join(value.split())


def is_allowed_draw_document_url(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.netloc.casefold() == DRAW_DOCUMENT_HOST
        and parsed.path.startswith(DRAW_DOCUMENT_PREFIX)
        and parsed.path.casefold().endswith(".pdf")
    )


def _text(element: Tag | None) -> str | None:
    if element is None:
        return None
    value = normalize_text(element.get_text(" ", strip=True))
    return value or None


def _extract_year(soup: BeautifulSoup, expected_year: int | None) -> int | None:
    if expected_year is not None:
        return expected_year
    title = _text(soup.find("title")) or ""
    match = re.search(r"\b(20\d{2})\b", title)
    if match:
        return int(match.group(1))
    return None


def _parse_dates(date_text: str | None, year: int | None) -> tuple[date | None, date | None]:
    if not date_text or year is None:
        return None, None
    match = DATE_RANGE_PATTERN.search(date_text.upper())
    if not match:
        return None, None
    end_month = MONTHS.get(match.group("end_month").upper())
    start_month_name = match.group("start_month") or match.group("end_month")
    start_month = MONTHS.get(start_month_name.upper())
    if start_month is None or end_month is None:
        return None, None
    start_day = int(match.group("start_day"))
    end_day = int(match.group("end_day"))
    end_year = year + 1 if end_month < start_month else year
    try:
        return date(year, start_month, start_day), date(end_year, end_month, end_day)
    except ValueError:
        return None, None


def _summary_cells(detail_row: Tag) -> list[str]:
    summary_row = detail_row.find_previous_sibling("tr")
    if not isinstance(summary_row, Tag):
        return []
    return [normalize_text(cell.get_text(" ", strip=True)) for cell in summary_row.find_all("td", recursive=False)]


def _draw_date_text(detail_row: Tag) -> str | None:
    for item in detail_row.find_all("li"):
        label = _text(item.find("strong"))
        if label and label.casefold().rstrip(":") == "draw date":
            full = _text(item)
            if full:
                return normalize_text(full.removeprefix(label).lstrip(":")) or None
    return None


def _event_link(detail_row: Tag) -> str | None:
    for anchor in detail_row.find_all("a", href=True):
        href = str(anchor["href"])
        parsed = urlparse(href)
        if parsed.scheme == "https" and parsed.netloc.casefold() == "bwfbadminton.com" and parsed.path.startswith("/events/"):
            return href
    return None


def _draw_documents(detail_row: Tag) -> Iterable[CalendarDocumentLink]:
    for anchor in detail_row.select(".cal-download-file-details .doc-type-name a[href]"):
        href = str(anchor["href"])
        label = _text(anchor) or ""
        if DRAW_LABEL_PATTERN.search(label) and is_allowed_draw_document_url(href):
            yield CalendarDocumentLink(label=label, url=href)


def parse_corporate_calendar_html(html: bytes, *, expected_year: int | None = None) -> list[CorporateCalendarEntry]:
    """Parse only BWF Corporate calendar event detail rows and direct BWF draw links.

    The parser intentionally returns raw calendar metadata. Senior/Para/junior eligibility is
    applied by the ingestion service before persistence or any draw document retrieval.
    """
    soup = BeautifulSoup(html, "html.parser")
    year = _extract_year(soup, expected_year)
    entries: list[CorporateCalendarEntry] = []
    for detail_row in soup.select("tr.tr-tournament-detail[id]"):
        source_tournament_id = str(detail_row.get("id") or "").strip()
        cells = _summary_cells(detail_row)
        if not source_tournament_id or len(cells) < 7:
            continue
        name = cells[3]
        if not name:
            continue
        detail_title = _text(detail_row.select_one(".info-tournament h2")) or name
        date_text = _text(detail_row.select_one(".info-tournament .text-description"))
        start_date, end_date = _parse_dates(date_text, year)
        entries.append(
            CorporateCalendarEntry(
                source_tournament_id=source_tournament_id,
                name=detail_title,
                country_code=cells[1] or None,
                start_date=start_date,
                end_date=end_date,
                category=cells[5] or None,
                city=cells[6] or None,
                source_url=_event_link(detail_row),
                draw_date_text=_draw_date_text(detail_row),
                draw_documents=tuple(_draw_documents(detail_row)),
                raw_row={
                    "week": cells[0] or None,
                    "country_code": cells[1] or None,
                    "dates": cells[2] or None,
                    "name": detail_title,
                    "prize_money": cells[4] or None,
                    "category": cells[5] or None,
                    "city": cells[6] or None,
                    "draw_date": _draw_date_text(detail_row),
                },
            )
        )
    return entries


class BWFCorporateCalendarClient:
    """Fixed-source client for the user-authorised BWF Corporate calendar and draw PDFs."""

    def __init__(self, settings: Settings | None = None, client: httpx.Client | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = client or httpx.Client(
            timeout=self.settings.bwf_calendar_request_timeout_seconds,
            headers={"User-Agent": self.settings.bwf_calendar_user_agent, "Accept": "text/html,application/pdf"},
            follow_redirects=False,
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def fetch_calendar(self) -> CorporateCalendarResponse:
        response = self._client.get(CALENDAR_URL)
        response.raise_for_status()
        content = response.content
        if not content or len(content) > self.settings.bwf_calendar_max_bytes:
            raise ValueError("BWF calendar response is empty or exceeds the configured byte limit")
        if "html" not in (response.headers.get("content-type") or "").casefold():
            raise ValueError("BWF calendar response did not declare HTML content")
        return CorporateCalendarResponse(
            url=str(response.url),
            status_code=response.status_code,
            retrieved_at=utcnow(),
            content=content,
            content_hash=content_hash(content),
            content_type=response.headers.get("content-type"),
        )

    def fetch_draw_document(self, url: str) -> CorporateDocumentResponse:
        if not is_allowed_draw_document_url(url):
            raise ValueError("Draw document URL is outside the authorised BWF document boundary")
        with self._client.stream("GET", url) as response:
            response.raise_for_status()
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > self.settings.bwf_draw_document_max_bytes:
                    raise ValueError("BWF draw document exceeds the configured byte limit")
                chunks.append(chunk)
            content = b"".join(chunks)
        if not content.startswith(b"%PDF"):
            raise ValueError("BWF draw document did not have a PDF signature")
        declared_type = (response.headers.get("content-type") or "").casefold()
        if declared_type and "pdf" not in declared_type and "octet-stream" not in declared_type:
            raise ValueError("BWF draw document did not declare PDF-compatible content")
        return CorporateDocumentResponse(
            url=str(response.url),
            status_code=response.status_code,
            retrieved_at=utcnow(),
            content=content,
            content_hash=content_hash(content),
            content_type=response.headers.get("content-type"),
        )
