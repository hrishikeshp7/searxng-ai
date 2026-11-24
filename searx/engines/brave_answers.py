# SPDX-License-Identifier: AGPL-3.0-or-later
"""Engine to answer queries using Brave Answers API (AI Mode).

.. _Brave Answers API: https://api.search.brave.com/
"""

import json
import logging
import os
import typing as t
import urllib.parse
import urllib.request
from urllib.parse import urlsplit

from markdown_it import MarkdownIt

from searx.exceptions import SearxEngineAPIException
from searx.result_types import EngineResults, BraveAnswer, MainResult

if t.TYPE_CHECKING:
    from searx.extended_types import SXNG_Response
    from searx.search.processors import OnlineParams

logger = logging.getLogger("searx.engines.brave_answers")

about = {
    "website": "https://api.search.brave.com/",
    "wikidata_id": None,
    "official_api_documentation": "https://api.search.brave.com/res/v1/chat/completions",
    "use_official_api": True,
    "require_api_key": True,
    "results": "JSON",
}

api_key: str = ""
categories = ["ai mode"]
paging = False
safesearch = True
timeout = 30.0

base_url = "https://api.search.brave.com/res/v1/chat/completions"
_markdown = MarkdownIt("commonmark", {"html": False, "typographer": True}).enable("table")


def setup(_: dict[str, t.Any]) -> bool | None:
    """Initialize the engine."""
    global api_key
    if not api_key:
        api_key = (
            os.environ.get("BRAVE_ANSWERS_API_KEY", "")
            or os.environ.get("BRAVE_API_KEY", "")
            or os.environ.get("SEARXNG_BRAVE_API_KEY", "")
        )
    if not api_key:
        raise SearxEngineAPIException("No Brave API key provided (set BRAVE_ANSWERS_API_KEY or BRAVE_API_KEY)")


def request(query: str, params: "OnlineParams") -> None:
    """Prepare POST request to Brave chat completions."""
    params["url"] = base_url
    params["method"] = "POST"
    params["headers"]["X-Subscription-Token"] = api_key
    params["headers"]["Content-Type"] = "application/json"
    params["headers"]["Accept"] = "application/json"
    params["raise_for_httperror"] = False

    payload = {
        "model": "brave",
        "messages": [{"role": "user", "content": query}],
        "stream": False,
    }
    params["data"] = json.dumps(payload).encode("utf-8")


def _extract_domain(url: str) -> str:
    try:
        netloc = urlsplit(url).netloc.lower()
        return netloc[4:] if netloc.startswith("www.") else netloc
    except Exception:
        return ""


def _call_groq_fallback(query: str) -> str | None:
    """Fallback if Brave Answers returns OPTION_NOT_IN_PLAN, using Groq + Brave grounding context."""
    groq_key = os.environ.get("SEARXNG_AI_OVERVIEW_API_KEY", "")
    groq_base = os.environ.get("SEARXNG_AI_OVERVIEW_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
    groq_model = os.environ.get("SEARXNG_AI_OVERVIEW_MODEL", "openai/gpt-oss-20b")
    if not groq_key:
        return None

    grounding_text = ""
    try:
        context_url = f"https://api.search.brave.com/res/v1/llm/context?q={urllib.parse.quote_plus(query)}"
        ctx_req = urllib.request.Request(
            context_url,
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
        )
        with urllib.request.urlopen(ctx_req, timeout=5) as r:
            ctx_data = json.loads(r.read().decode("utf-8"))
            generic = ctx_data.get("grounding", {}).get("generic", [])
            snippets = []
            for item in generic[:5]:
                title = item.get("title", "")
                snips = "\n".join(item.get("snippets", []))
                snippets.append(f"Source: {title}\n{snips}")
            grounding_text = "\n\n".join(snippets)
    except Exception as e:
        logger.warning("Brave LLM context retrieval failed: %s", e)

    prompt = (
        f"Answer this query clearly, accurately and neutrally based on search grounding:\n"
        f"Query: {query}\n\nGrounding sources:\n{grounding_text}"
        if grounding_text
        else f"Answer this search query comprehensively:\n{query}"
    )

    groq_payload = json.dumps({
        "model": groq_model,
        "messages": [
            {
                "role": "system",
                "content": "You are SearXNG AI Mode assistant. Provide clear, direct, informative answers in Markdown with citations.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 800,
    }).encode("utf-8")

    try:
        groq_req = urllib.request.Request(
            f"{groq_base}/chat/completions",
            data=groq_payload,
            headers={
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(groq_req, timeout=8) as r:
            g_data = json.loads(r.read().decode("utf-8"))
            ans = g_data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if ans:
                notice = (
                    "\n\n---\n*💡 Note: Answer synthesized using Brave LLM Context. "
                    "To enable native Brave Answers on this key, toggle the **Answers** plan at "
                    "[api-dashboard.search.brave.com](https://api-dashboard.search.brave.com/app/plans).*"
                )
                return ans + notice
    except Exception as e:
        logger.warning("Groq fallback call failed: %s", e)
    return None


def response(resp: "SXNG_Response") -> EngineResults:
    res = EngineResults()
    query = resp.search_params.get("query", "")

    if resp.status_code == 200:
        data = resp.json()
        choices = data.get("choices") or []
        if choices:
            answer_text = choices[0].get("message", {}).get("content", "")
            raw_citations = data.get("citations") or []
            sources = []
            for c in raw_citations:
                u = c.get("url") or ""
                if u:
                    sources.append({
                        "url": u,
                        "title": c.get("title") or u,
                        "domain": _extract_domain(u),
                    })
            html = _markdown.render(answer_text)
            res.add(BraveAnswer(html=html, sources=sources))
            res.add(MainResult(
                url="https://search.brave.com",
                title=f"Brave AI: {query}",
                content=answer_text[:350] + ("..." if len(answer_text) > 350 else ""),
            ))
            return res

    # Status not 200 (e.g. OPTION_NOT_IN_PLAN before user toggles Answers in dashboard)
    try:
        err_json = resp.json()
    except Exception:
        err_json = {}

    err_code = err_json.get("error", {}).get("code", "")
    fallback_answer = None
    if err_code == "OPTION_NOT_IN_PLAN":
        fallback_answer = _call_groq_fallback(query)

    if fallback_answer:
        html = _markdown.render(fallback_answer)
        res.add(BraveAnswer(html=html, sources=[]))
        res.add(MainResult(
            url="https://api-dashboard.search.brave.com/app/plans",
            title=f"AI Mode: {query}",
            content=fallback_answer[:350],
        ))
        return res

    # Otherwise display guidance to activate plan
    notice = (
        "### Brave Answers API Plan Setup\n\n"
        "Your Brave API key is connected, but the **Answers** plan option is not yet activated on this key.\n\n"
        "1. Open your **[Brave Search API Dashboard](https://api-dashboard.search.brave.com/app/plans)**.\n"
        "2. Add or toggle the **Answers** plan for your key.\n"
        "3. Search again in **AI Mode** to get direct Brave Answers.\n\n"
        "*(Standard AI overviews remain active in the **General** tab).* "
    )
    html = _markdown.render(notice)
    res.add(BraveAnswer(html=html, sources=[]))
    return res
