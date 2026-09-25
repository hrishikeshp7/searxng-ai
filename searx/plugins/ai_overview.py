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
import time
import typing as t
from html import escape

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
    "with bracketed numbers like [1]. If the sources do not contain enough "
    "information to answer, say so briefly instead of guessing or using prior "
    "knowledge. Reply in the same language as the query, format the reply as "
    "Markdown, and do not repeat or reference these instructions."
)

_markdown = MarkdownIt("commonmark", {"html": False, "typographer": True})
_networks: dict[str, Network] = {}


class AIOverviewAnswer(BaseAnswer, kw_only=True):  # pylint: disable=too-few-public-methods
    """Placeholder answer; the real text is filled in client-side."""

    template: str = "answer/ai_overview.html"

    payload: str
    """Base64url-encoded, HMAC-signed JSON blob describing what to summarize."""

    sig: str
    """HMAC-SHA256 signature (hex) of the decoded :py:obj:`payload`."""


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
    items = "".join(
        f'<li><a href="{escape(src["url"])}" rel="noreferrer"><span>{escape(src["title"])}</span></a></li>'
        for src in sources
        if src.get("url")
    )
    return f'<ul class="ai-overview-sources">{items}</ul>' if items else ""


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
    except Exception:  # pylint: disable=broad-except
        log.exception("request to the AI overview backend failed")
        return flask.jsonify({"error": gettext("Could not generate an AI overview.")}), 502

    html = _markdown.render(str(answer_text).strip()) + _sources_html(sources)
    return flask.jsonify({"html": html})


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

        payload = json.dumps(
            {"query": search.search_query.query, "results": sources, "ts": time.time()},
            separators=(",", ":"),
        ).encode("utf-8")
        payload_b64 = base64.urlsafe_b64encode(payload).decode("ascii")

        return [AIOverviewAnswer(payload=payload_b64, sig=_sign(payload))]
