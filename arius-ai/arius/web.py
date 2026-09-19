"""Web fetching & readable-text extraction for ARIUS's web-learning skill.

Two backends:
  * "urllib"  - standard library only, fast, no JavaScript. Default.
  * "chrome"  - Playwright + Chromium, renders JavaScript-heavy pages.
                Optional: `pip install playwright && playwright install chromium`.

Only http/https URLs are allowed. Content is capped so a single page can't
exhaust memory. This is a *bounded reader*, not an unbounded web crawler.
"""

from __future__ import annotations

import gzip
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser

USER_AGENT = "ARIUS/0.1 (+local personal AI assistant)"
_BLOCK_TAGS = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "tr", "section", "article", "header", "footer"}
_SKIP_TAGS = {"script", "style", "noscript", "head", "template", "svg", "nav"}

URL_RE = re.compile(r"https?://[^\s'\"<>]+", re.IGNORECASE)


@dataclass
class WebPage:
    url: str
    title: str
    text: str

    @property
    def length(self) -> int:
        return len(self.text)

    def summary(self, limit: int = 240) -> str:
        body = " ".join(self.text.split())
        return body if len(body) <= limit else body[: limit - 1] + "…"


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self.title_parts: list[str] = []
        self.chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in _BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in _BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
            return
        if self._skip_depth:
            return
        stripped = data.strip()
        if stripped:
            self.chunks.append(stripped + " ")

    @property
    def title(self) -> str:
        return " ".join("".join(self.title_parts).split())

    @property
    def text(self) -> str:
        raw = "".join(self.chunks)
        lines = [ln.strip() for ln in raw.splitlines()]
        return "\n".join(ln for ln in lines if ln)


def _html_to_page(url: str, html: str) -> WebPage:
    parser = _TextExtractor()
    parser.feed(html)
    return WebPage(url=url, title=parser.title or url, text=parser.text)


def _validate(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"http/https URL만 학습할 수 있습니다: {url!r}")
    if not parsed.netloc:
        raise ValueError(f"올바르지 않은 URL입니다: {url!r}")


def fetch_urllib(url: str, timeout: int = 15, max_bytes: int = 2_000_000) -> WebPage:
    _validate(url)
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip", "Accept": "text/html,*/*"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (scheme validated above)
        raw = resp.read(max_bytes)
        if resp.headers.get("Content-Encoding") == "gzip":
            try:
                raw = gzip.decompress(raw)
            except OSError:
                pass
        charset = resp.headers.get_content_charset() or "utf-8"
    html = raw.decode(charset, errors="replace")
    return _html_to_page(url, html)


def fetch_chrome(url: str, timeout: int = 20) -> WebPage:
    _validate(url)
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "크롬(Chromium) 렌더링을 쓰려면 Playwright가 필요합니다: "
            "`pip install playwright && playwright install chromium`"
        ) from exc
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(user_agent=USER_AGENT)
            page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
            html = page.content()
        finally:
            browser.close()
    return _html_to_page(url, html)


def fetch(url: str, backend: str = "urllib", timeout: int = 15) -> WebPage:
    """Fetch a page with the chosen backend ('urllib' | 'chrome' | 'auto')."""
    if backend in ("chrome", "playwright"):
        return fetch_chrome(url, timeout=timeout)
    return fetch_urllib(url, timeout=timeout)


def extract_first_url(text: str) -> str | None:
    m = URL_RE.search(text)
    return m.group(0).rstrip(").,;") if m else None
