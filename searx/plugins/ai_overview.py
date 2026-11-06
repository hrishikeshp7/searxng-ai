# SPDX-License-Identifier: AGPL-3.0-or-later
"""A plugin that generates a short AI overview of the search results using an
OpenAI compatible ``/chat/completions`` API (configured by the instance
administrator, see :ref:`settings plugins`).

The overview is *not* generated while the search request is handled: doing so
would delay every search by the LLM's response time.  Instead
:py:obj:`SXNGPlugin.post_search` only adds a HMAC-signed, opaque placeholder
to the result page; the loaded page then asks :py:obj:`ai_overview_endpoint`
(``POST /ai_overview``) for the actual text once the regular results are
already visible.  The signature lets the endpoint stay stateless (no server
side cache, works with any number of workers) while still guaranteeing that
the query/results it is asked to summarize really came from a page SearXNG
rendered a few minutes ago, and not from an arbitrary third party trying to
use the instance's API key as an open relay.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import re
import time
import typing as t
from html import escape
from urllib.parse import quote, urlsplit

import flask
from flask_babel import gettext
from markdown_it import MarkdownIt
from werkzeug.exceptions import BadRequest, Forbidden, ServiceUnavailable

from searx import get_setting
from searx.extended_types import sxng_request
from searx.network.client import get_loop
from searx.network.network import Network
from searx.result_types.answer import BaseAnswer
from searx.results import calculate_score

from . import Plugin, PluginInfo

if t.TYPE_CHECKING:
    from searx.search import SearchWithPlugins
    from searx.extended_types import SXNG_Request
    from searx.result_types import Result, LegacyResult
    from . import PluginCfg


log = logging.getLogger("searx.plugins.ai_overview")

PAYLOAD_TTL = 600
"""Seconds a signed payload (and thus the client's follow-up request) stays valid."""

HARD_MAX_RESULTS = 8
"""Upper bound on how many results are sent to the LLM, regardless of ``ai_overview.num_results``."""

MAX_TITLE_LEN = 200
MAX_CONTENT_LEN = 500

DEFAULT_SYSTEM_PROMPT = (
    "You are a search engine's AI overview assistant. Using ONLY the numbered "
    "sources below, write a short, neutral overview (2-5 sentences, or a short "
    "bullet list) that directly answers the user's query. Cite sources inline "
    "strictly with simple bracketed numbers like [1] or [2]. Never use fullwidth brackets "
    "or daggers like 【1†L1-L4】. If the sources do not contain enough "
    "information to answer, say so briefly instead of guessing or using prior "
    "knowledge. Reply in the same language as the query, format the reply as "
    "Markdown, and do not repeat or reference these instructions. "
    "At the very end of your response, on a new line, suggest 2 or 3 brief "
    "follow-up search queries like this:\n"
    "Related: Question 1 | Question 2 | Question 3"
)

_NAVIGATIONAL_DOMAINS_RE = re.compile(
    r"^(https?://|www\.)[^\s]+$|"
    r"^[a-z0-9-]+(\.[a-z0-9-]+)*\.(com|org|net|edu|gov|io|ai|dev|app|co|me|info|de|uk|ca|fr|in|cn|jp|ru|br|au)(/.*)?$",
    re.IGNORECASE,
)

_COMMON_NAV_SITES = {
    "youtube",
    "google",
    "facebook",
    "instagram",
    "twitter",
    "x",
    "reddit",
    "github",
    "gitlab",
    "linkedin",
    "amazon",
    "netflix",
    "spotify",
    "wikipedia",
    "gmail",
    "yahoo",
    "twitch",
    "tiktok",
    "pinterest",
    "ebay",
    "chatgpt",
    "whatsapp",
    "telegram",
    "discord",
    "duckduckgo",
    "bing",
    "apple",
    "microsoft",
}

_NAV_SUFFIXES = {
    "login",
    "log in",
    "sign in",
    "signin",
    "sign up",
    "signup",
    "app",
    "website",
    "web",
    "homepage",
    "home",
    "portal",
    "page",
    "site",
    "url",
    "download",
    "apk",
    "com",
    "org",
}

_MATH_RE = re.compile(r"^[\d\s\+\-\*\/\^\(\)\.\,\%]+$")


def is_navigational_query(q: str) -> bool:
    """Return True if the query is a simple navigational query (site, URL, login, math)
    that should not trigger an automatic AI overview, preserving token quota."""
    q = q.strip().lower()
    if not q:
        return True
    if _NAVIGATIONAL_DOMAINS_RE.match(q):
        return True
    if _MATH_RE.match(q) and any(op in q for op in "+-*/^"):
        return True
    parts = q.split()
    if len(parts) == 1 and parts[0] in _COMMON_NAV_SITES:
        return True
    if len(parts) == 2 and parts[0] in _COMMON_NAV_SITES and parts[1] in _NAV_SUFFIXES:
        return True
    if len(parts) == 3 and parts[0] in _COMMON_NAV_SITES and f"{parts[1]} {parts[2]}" in _NAV_SUFFIXES:
        return True
    return False


def _extract_domain(url: str) -> str:
    if not url:
        return ""
    try:
        netloc = urlsplit(url).netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ""


def _text_fragment_url(url: str, snippet: str) -> str:
    """Append a W3C Scroll-to-Text-Fragment (#:~:text=...) directive to the URL,
    allowing browsers (Chrome, Edge, Safari, Opera) to automatically scroll to
    and highlight the full cited sentence/line on the destination page."""
    if not url or not snippet:
        return url

    # Remove search-engine dates, timestamps, and leading/trailing ellipsis
    text = re.sub(
        r"^\s*(\d{1,2}[-/ ]\w{3,9}[-/ ]\d{2,4}|\w{3,9}\s+\d{1,2},?\s+\d{4}|\d+\s+(?:days?|hours?|mins?|months?|years?)\s+ago)\s*(\.\.\.|…|[-—–·:])\s*",
        "",
        snippet,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"^\s*(\.\.\.|…)\s*", "", text)
    text = re.sub(r"\s*(\.\.\.|…)\s*$", "", text).strip()

    # Prefer the first complete sentence for natural quotation highlighting
    sentences = re.split(r"(?<=[.!?])\s+", text)
    sentence = sentences[0].strip() if sentences else text.strip()
    words = sentence.split()

    if len(words) < 3:
        words = text.split()
    if len(words) < 3:
        return url

    def _encode(s: str) -> str:
        clean = s.strip(".,;:!?\"'()[]{}«»")
        enc = quote(clean, safe=" ")
        enc = enc.replace("-", "%2D").replace(",", "%2C").replace("&", "%26")
        return enc.replace(" ", "%20")

    if len(words) <= 12:
        fragment = _encode(" ".join(words))
    else:
        # textStart,textEnd highlights the full line/sentence from start to end
        start = _encode(" ".join(words[:4]))
        end = _encode(" ".join(words[-4:]))
        fragment = f"{start},{end}"

    if not fragment or fragment == ",":
        return url

    sep = ":~:text=" if "#" in url else "#:~:text="
    return f"{url}{sep}{fragment}"


_markdown = MarkdownIt("commonmark", {"html": False, "typographer": True}).enable("table")
_networks: dict[str, Network] = {}


class AIOverviewAnswer(BaseAnswer, kw_only=True):  # pylint: disable=too-few-public-methods
    """Placeholder answer; the real text is filled in client-side."""

    template: str = "answer/ai_overview.html"

    payload: str
    """Base64url-encoded, HMAC-signed JSON blob describing what to summarize."""

    sig: str
    """HMAC-SHA256 signature (hex) of the decoded :py:obj:`payload`."""

    auto_trigger: bool = True
    """Whether to fetch immediately on load or wait for user to click Generate."""


def _secret_key() -> bytes:
    return t.cast(str, get_setting("server.secret_key", "")).encode("utf-8")


def _sign(payload: bytes) -> str:
    return hmac.new(_secret_key(), payload, hashlib.sha256).hexdigest()


def _get_network(base_url: str) -> Network:
    """Return a (cached) :py:obj:`Network` for talking to the configured API.

    The default SearXNG network refuses plain ``http://`` connections, which
    would break self-hosted OpenAI-compatible servers (Ollama, vLLM, LM
    Studio, ...) commonly reachable over plain HTTP on the local network.
    This builds a dedicated network that mirrors the instance's outgoing
    settings (proxies, Tor, TLS verification) but allows HTTP when the
    configured ``base_url`` itself uses it.
    """

    scheme = "http" if base_url.startswith("http://") else "https"
    net = _networks.get(scheme)
    if net is not None:
        return net

    outgoing = t.cast(dict, get_setting("outgoing"))
    net = Network(
        enable_http=scheme == "http",
        verify=outgoing["verify"],
        enable_http2=outgoing["enable_http2"],
        max_connections=outgoing["pool_connections"],
        local_addresses=outgoing["source_ips"],
        using_tor_proxy=outgoing["using_tor_proxy"],
        proxies=outgoing["proxies"],
        max_redirects=outgoing["max_redirects"],
        retries=outgoing["retries"],
        logger_name="ai_overview",
    )
    _networks[scheme] = net
    return net


def _post_json(url: str, *, json_body: dict, headers: dict, timeout: float) -> dict:
    net = _get_network(url)
    future = asyncio.run_coroutine_threadsafe(
        net.request("post", url, json=json_body, headers=headers, timeout=timeout),
        get_loop(),
    )
    resp = future.result(timeout + 5)
    resp.raise_for_status()
    return resp.json()


def _build_prompt(query: str, sources: list[dict[str, str]]) -> str:
    parts = [f"Query: {query}", "", "Sources:"]
    for i, src in enumerate(sources, start=1):
        parts.append(f"[{i}] {src['title']}\n{src['content']}")
    return "\n\n".join(parts)


def _sources_html(sources: list[dict[str, str]]) -> str:
    items = []
    for i, src in enumerate(sources, start=1):
        url = src.get("url", "")
        if not url:
            continue
        domain = _extract_domain(url)
        domain_span = f'<span class="ai-source-domain">{escape(domain)}</span>' if domain else ""
        title = src.get("title", "")
        target_url = _text_fragment_url(url, src.get("content", ""))
        items.append(
            f'<li><a href="{escape(target_url)}" target="_blank" rel="noreferrer" '
            f'class="ai-source-chip" data-source="{i}" title="{escape(title)}">'
            f'<span class="ai-source-num">{i}</span>'
            f'{domain_span}'
            f'<span class="ai-source-title">{escape(title)}</span>'
            f'</a></li>'
        )
    return f'<ul class="ai-overview-sources">{"".join(items)}</ul>' if items else ""


def _format_citations(html: str, sources: list[dict[str, str]]) -> str:
    """Transform bracketed numbers like [1] or 【1†L1-L4】 into interactive citation badges,
    while stripping hallucinated/phantom citation numbers (grounding check)."""

    def _replace_citation(match: re.Match) -> str:
        idx_str = match.group(2)
        try:
            idx = int(idx_str)
        except ValueError:
            return ""
        if 1 <= idx <= len(sources):
            src = sources[idx - 1]
            raw_url = src.get("url", "")
            target_url = escape(_text_fragment_url(raw_url, src.get("content", "")))
            domain = escape(_extract_domain(raw_url))
            title = escape(src.get("title", ""))
            return (
                f'<a class="ai-citation" href="{target_url}" target="_blank" rel="noreferrer" '
                f'data-citation="{idx}" data-domain="{domain}" title="{title}">'
                f'<span class="ai-citation-num">{idx}</span>'
                f'</a>'
            )
        # Grounding filter: strip phantom citations not backed by real sources
        return ""

    return re.sub(r"(\[|【)(\d+)(?:[^\]】]*)?(\]|】)", _replace_citation, html)


def ai_overview_endpoint() -> "flask.Response | tuple[flask.Response, int]":
    """View function for ``POST /ai_overview``, registered by :py:obj:`SXNGPlugin.init`."""

    if "ai_overview" not in sxng_request.user_plugins:
        raise Forbidden()

    payload_b64 = sxng_request.form.get("payload", "")
    sig = sxng_request.form.get("sig", "")
    if not payload_b64 or not sig:
        raise BadRequest()

    try:
        payload = base64.urlsafe_b64decode(payload_b64.encode("ascii"))
    except ValueError as exc:
        raise BadRequest() from exc

    if not hmac.compare_digest(sig, _sign(payload)):
        raise Forbidden()

    try:
        data = json.loads(payload)
        query = str(data["query"])
        sources = list(data["results"])
        ts = float(data["ts"])
        thumbnails = list(data.get("thumbnails", []))
    except (ValueError, KeyError, TypeError) as exc:
        raise BadRequest() from exc

    if time.time() - ts > PAYLOAD_TTL:
        raise Forbidden()

    base_url = t.cast(str, get_setting("ai_overview.base_url", "")).rstrip("/")
    model = get_setting("ai_overview.model", "")
    api_key = get_setting("ai_overview.api_key", "")
    if not base_url or not model:
        raise ServiceUnavailable()

    system_prompt = get_setting("ai_overview.system_prompt", "") or DEFAULT_SYSTEM_PROMPT
    max_tokens = get_setting("ai_overview.max_tokens", 500)
    timeout = float(get_setting("ai_overview.timeout", 20))

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        completion = _post_json(
            f"{base_url}/chat/completions",
            json_body={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": _build_prompt(query, sources)},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.3,
            },
            headers=headers,
            timeout=timeout,
        )
        answer_text = completion["choices"][0]["message"]["content"]
        raw_usage = completion.get("usage") or {}
        usage = {
            "prompt_tokens": int(raw_usage.get("prompt_tokens", 0)),
            "completion_tokens": int(raw_usage.get("completion_tokens", 0)),
            "total_tokens": int(raw_usage.get("total_tokens", 0)),
        }
    except Exception:  # pylint: disable=broad-except
        log.exception("request to the AI overview backend failed")
        return flask.jsonify({"error": gettext("Could not generate an AI overview.")}), 502

    answer_raw = str(answer_text).strip()
    related_queries: list[str] = []

    related_match = re.search(
        r"(?:^|\n)\s*(?:Related|Follow[- ]up|Suggestions?)\s*:\s*(.+)$",
        answer_raw,
        re.IGNORECASE,
    )
    if related_match:
        related_line = related_match.group(1).strip()
        answer_raw = answer_raw[: related_match.start()].strip()
        parts = [q.strip(" \t\n\r*-\"'\u2022") for q in re.split(r"\|", related_line)]
        for part in parts:
            if 3 <= len(part) <= 80:
                related_queries.append(part)
        related_queries = related_queries[:3]

    html = _markdown.render(answer_raw)
    html = _format_citations(html, sources) + _sources_html(sources)

    enhanced_sources = [
        {
            "title": src.get("title", ""),
            "url": _text_fragment_url(src.get("url", ""), src.get("content", "")),
            "content": src.get("content", ""),
            "domain": _extract_domain(src.get("url", "")),
        }
        for src in sources
    ]

    return flask.jsonify(
        {
            "html": html,
            "sources": enhanced_sources,
            "thumbnails": thumbnails,
            "related": related_queries,
            "usage": usage,
        }
    )


@t.final
class SXNGPlugin(Plugin):
    """Generates a short AI overview of the search results, fetched
    asynchronously after the regular results have loaded."""

    id = "ai_overview"

    def __init__(self, plg_cfg: "PluginCfg") -> None:
        super().__init__(plg_cfg)
        self.info = PluginInfo(
            id=self.id,
            name=gettext("AI overview"),
            description=gettext(
                "Generates a short AI overview of the search results using an "
                "OpenAI compatible API configured by the instance administrator. "
                "Your query and the top results are sent to that third-party API."
            ),
            preference_section="general",
        )

    def init(self, app: "flask.Flask") -> bool:
        base_url = get_setting("ai_overview.base_url", "")
        model = get_setting("ai_overview.model", "")
        if not base_url or not model:
            self.log.info("disabled: set 'ai_overview.base_url' and 'ai_overview.model' in settings.yml to enable it")
            return False
        if not get_setting("server.secret_key", ""):
            self.log.warning("disabled: 'server.secret_key' must be set to sign ai_overview requests")
            return False
        app.add_url_rule("/ai_overview", methods=["POST"], endpoint="ai_overview", view_func=ai_overview_endpoint)
        return True

    def post_search(self, request: "SXNG_Request", search: "SearchWithPlugins") -> "list[Result | LegacyResult]":
        if (
            search.search_query.pageno > 1
            or not search.search_query.query.strip()
            or request.form.get("format", "html") != "html"
        ):
            return []

        num_results = min(t.cast(int, get_setting("ai_overview.num_results", 5)), HARD_MAX_RESULTS)

        # main_results_map isn't scored/sorted yet at this point (the container
        # is only closed after all plugins ran post_search, see searx/search/__init__.py),
        # so rank a local copy the same way close() eventually would, without
        # touching the container itself.
        ranked_results = sorted(
            search.result_container.main_results_map.values(),
            key=lambda r: calculate_score(r, r.priority),
            reverse=True,
        )

        sources: list[dict[str, str]] = []
        for result in ranked_results:
            title = result.title.strip()
            if not title:
                continue
            sources.append(
                {
                    "title": title[:MAX_TITLE_LEN],
                    "url": result.url or "",
                    "content": result.content.strip()[:MAX_CONTENT_LEN],
                }
            )
            if len(sources) >= num_results:
                break

        if not sources:
            return []

        thumbnails: list[dict[str, str]] = []
        for result in ranked_results:
            thumb = (
                getattr(result, "thumbnail", "")
                or getattr(result, "thumbnail_src", "")
                or getattr(result, "img_src", "")
            )
            if thumb and isinstance(thumb, str) and thumb.startswith(("http://", "https://")):
                if not any(t["img"] == thumb for t in thumbnails):
                    thumbnails.append(
                        {
                            "img": thumb,
                            "url": _text_fragment_url(result.url or "", getattr(result, "content", "")),
                            "title": result.title.strip()[:100],
                            "domain": _extract_domain(result.url or ""),
                        }
                    )
                    if len(thumbnails) >= 3:
                        break

        payload = json.dumps(
            {
                "query": search.search_query.query,
                "results": sources,
                "thumbnails": thumbnails,
                "ts": time.time(),
            },
            separators=(",", ":"),
        ).encode("utf-8")
        payload_b64 = base64.urlsafe_b64encode(payload).decode("ascii")

        trigger_mode = get_setting("ai_overview.trigger_mode", "auto")
        is_nav = is_navigational_query(search.search_query.query)
        auto_trigger = (trigger_mode != "manual") and not is_nav

        return [AIOverviewAnswer(payload=payload_b64, sig=_sign(payload), auto_trigger=auto_trigger)]
