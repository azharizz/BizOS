"""Server-side web reading, used when the Chrome extension isn't connected.

Every URL is checked first: http(s) only, and never an internal or private address (the agent decides what to
fetch, and page text can try to steer it, so it must not be able to reach this machine or the office network).
"""
import ipaddress
import socket
import ssl
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote_plus, urlparse

import httpx
import truststore

_transport: httpx.AsyncBaseTransport | None = None  # tests swap in a mock
TLS = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)  # the OS trust store, like the browser (fills incomplete chains)
BLOCKED_HOST = "block.wandera.com"  # corporate web filter seen on this network
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) BizOS/0.1"


def search_url(query: str) -> str:
    return f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"


def check_url(url: str) -> str:
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError(f"only http(s) web pages can be opened, not {url[:60]}")
    try:
        addrs = {info[4][0] for info in socket.getaddrinfo(u.hostname, None)}
    except socket.gaierror:
        raise ValueError(f"cannot resolve {u.hostname}")
    for a in addrs:
        ip = ipaddress.ip_address(a)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise ValueError(f"{u.hostname} is an internal address; refusing to fetch it")
    return url


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template"}

    def __init__(self):
        super().__init__()
        self.parts, self.title, self._skip, self._in_title = [], "", 0, False

    def handle_starttag(self, tag, attrs):
        self._skip += tag in self.SKIP
        self._in_title = tag == "title"

    def handle_endtag(self, tag):
        self._skip -= tag in self.SKIP and self._skip > 0
        self._in_title = False if tag == "title" else self._in_title

    def handle_data(self, data):
        if self._in_title:
            self.title += data.strip()
        elif not self._skip and data.strip():
            self.parts.append(data.strip())


def page_text(html: str) -> dict:
    p = _Text()
    p.feed(html)
    return {"title": p.title, "text": " ".join(p.parts)[:30000]}


class _Results(HTMLParser):
    """DuckDuckGo's no-JS results page: a.result__a (title + link) followed by .result__snippet."""

    def __init__(self):
        super().__init__()
        self.rows, self._field = [], None

    def handle_starttag(self, tag, attrs):
        cls = dict(attrs).get("class") or ""
        if tag == "a" and "result__a" in cls:
            href = dict(attrs).get("href", "")
            target = parse_qs(urlparse(href).query).get("uddg", [href])[0]
            self.rows.append({"title": "", "url": target if target.startswith("http") else "https:" + target, "snippet": ""})
            self._field = "title"
        elif "result__snippet" in cls and self.rows:
            self._field = "snippet"

    def handle_endtag(self, tag):
        if tag in ("a", "div", "td"):
            self._field = None

    def handle_data(self, data):
        if self._field and self.rows:
            self.rows[-1][self._field] = (self.rows[-1][self._field] + " " + data.strip()).strip()


def parse_results(html: str) -> list[dict]:
    p = _Results()
    p.feed(html)
    return [r for r in p.rows if r["title"]][:10]


async def _get(url: str) -> str:
    async with httpx.AsyncClient(transport=_transport, verify=TLS, timeout=15, follow_redirects=False, headers={"User-Agent": UA}) as c:
        for _ in range(4):  # follow redirects by hand so every hop passes the guard
            r = await c.get(check_url(url))
            if r.is_redirect and r.headers.get("location"):
                url = str(r.url.join(r.headers["location"]))
                if BLOCKED_HOST in (urlparse(url).hostname or ""):
                    raise ValueError("blocked by your network's web filter; try another source")
                continue
            r.raise_for_status()
            if "<title>Forbidden Website</title>" in r.text[:2000]:
                raise ValueError("blocked by your network's web filter; try another source")
            return r.text
    raise ValueError("too many redirects")


async def fetch(url: str) -> dict:
    return {"url": url, **page_text(await _get(url))}


async def search(query: str) -> list[dict]:
    return parse_results(await _get(search_url(query)))
