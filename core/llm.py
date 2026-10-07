"""One way for every section to ask a model for a structured summary, whatever the provider.

  generate(cfg, system=..., user=..., schema=..., name=..., web_searches=N) -> (result, info)

`cfg` is the section's resolved llm settings (see sections.resolve_llm):
  provider "anthropic": Claude via the Anthropic SDK. The result comes back through a strict `publish_<name>`
      tool; web search is Anthropic's server-side tool.
  provider "openai": any OpenAI-compatible server (llama.cpp / llama-swap, LM Studio, Ollama's /v1). The result
      is a json_schema completion; web search is a local DuckDuckGo + page-fetch tool loop.

`info` has the token usage and the URLs the model actually saw (for dropping hallucinated links).
Usage is reported through `on_usage(usage, ok)` even when a call fails, because failed calls are billed too.
"""

import json
import re
import time

from core.common import log

DEFAULT_MODEL = "claude-sonnet-5-5"


def generate(cfg, *, system, user, schema, name, description="Publish the finished result.", web_searches=0, on_usage=None):
    provider = cfg.get("provider", "anthropic")
    if provider == "anthropic":
        return _anthropic(cfg, system, user, schema, name, description, web_searches, on_usage)
    if provider == "openai":
        return _openai(cfg, system, user, schema, name, web_searches, on_usage)
    raise ValueError(f"unknown llm provider {provider!r}")


def _empty_usage(model):
    return {"model": model, "requests": 0, "input": 0, "cache_read": 0, "output": 0, "searches": 0, "fetches": 0}


# ---------------------------------------------------------------- Anthropic


def _anthropic(cfg, system, user, schema, name, description, web_searches, on_usage):
    import anthropic

    model = cfg.get("model", DEFAULT_MODEL)
    client = anthropic.Anthropic(timeout=cfg.get("timeout_s", 600), max_retries=3)
    tool_name = f"publish_{name}"
    publish = {"name": tool_name, "description": description, "strict": True, "input_schema": schema}
    tools = [publish]
    if web_searches:
        tools.insert(0, {"type": "web_search_20260209", "name": "web_search", "max_uses": web_searches})
    system = f"{system}\n\nWhen you're done, call {tool_name} exactly once with the finished result."
    messages = [{"role": "user", "content": user}]
    usage = _empty_usage(model)
    seen_urls = set()
    started = time.time()

    def finish(ok):
        log(f"{name}: {usage['requests']} requests, {usage['input']:,} in + {usage['cache_read']:,} cached + "
            f"{usage['output']:,} out tokens, {usage['searches']} searches, {time.time() - started:.0f}s ({model})")
        if on_usage:
            try:
                on_usage(usage, ok)
            except Exception as e:  # logging must never cost us a finished result
                log(f"usage logging failed: {e}")

    for _ in range(8):  # covers pause_turn resumes and one nudge
        try:
            with client.beta.messages.stream(
                model=model,
                max_tokens=cfg.get("max_tokens", 32000),
                system=system,
                thinking={"type": "adaptive"},
                output_config={"effort": cfg.get("effort", "medium")},
                tools=tools,
                messages=messages,
                # On a safety-classifier decline, the API reruns the request on Anthropic's recommended fallback model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            ) as stream:
                response = stream.get_final_message()
        except Exception:
            finish(False)
            raise
        u = response.usage
        usage["requests"] += 1
        usage["input"] += (u.input_tokens or 0) + (getattr(u, "cache_creation_input_tokens", 0) or 0)
        usage["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0
        usage["output"] += u.output_tokens or 0
        stu = getattr(u, "server_tool_use", None)
        if stu:
            usage["searches"] += getattr(stu, "web_search_requests", 0) or 0
            usage["fetches"] += getattr(stu, "web_fetch_requests", 0) or 0

        if response.stop_reason == "refusal":
            finish(False)
            raise RuntimeError(f"{name} declined: {response.stop_details}")
        for block in response.content:
            if block.type == "web_search_tool_result" and isinstance(block.content, list):
                seen_urls.update(r.url for r in block.content if getattr(r, "url", None))
        for block in response.content:
            if block.type == "tool_use" and block.name == tool_name:
                finish(True)
                return block.input, {"usage": usage, "seen_urls": seen_urls}
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason == "pause_turn":
            continue  # server-side search loop paused; resend to resume
        if response.stop_reason == "max_tokens":
            finish(False)
            raise RuntimeError(f"{name} hit max_tokens before publishing")
        messages.append({"role": "user", "content": f"Now call {tool_name} with the finished result."})
    finish(False)
    raise RuntimeError(f"{name}: model never called {tool_name}")


# ---------------------------------------------------------------- OpenAI-compatible (local models)


def _client(cfg):
    from openai import OpenAI

    return OpenAI(base_url=cfg["base_url"], api_key=cfg.get("api_key", "local"), timeout=cfg.get("timeout_s", 1200), max_retries=3)


def _strip_think(text):
    # Some servers leave Qwen's <think> block in the content instead of a separate reasoning field.
    return re.sub(r"(?s)<think>.*?</think>", "", text or "").strip()


def _openai(cfg, system, user, schema, name, web_searches, on_usage):
    model = cfg["model"]
    api = _client(cfg)
    usage = _empty_usage(model)
    seen_urls = set()
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    common = {"model": model, "temperature": cfg.get("temperature", 0.3), "max_tokens": cfg.get("max_tokens", 16000)}

    def count(r):
        usage["requests"] += 1
        if r.usage:
            usage["input"] += r.usage.prompt_tokens or 0
            usage["output"] += r.usage.completion_tokens or 0

    try:
        if web_searches:
            web = LocalWeb(seen_urls)
            for step in range(cfg.get("max_steps", 14)):
                r = api.chat.completions.create(**common, messages=messages, tools=LocalWeb.TOOLS)
                count(r)
                msg = r.choices[0].message
                calls = msg.tool_calls or []
                messages.append({
                    "role": "assistant", "content": _strip_think(msg.content),
                    **({"tool_calls": [tc.model_dump() for tc in calls]} if calls else {}),
                })
                if not calls:
                    break
                for tc in calls:
                    if tc.function.name == "web_search":
                        if usage["searches"] >= web_searches:
                            result = "Search limit reached: write up what you have."
                        else:
                            usage["searches"] += 1
                            result = web.call(tc.function.name, tc.function.arguments)
                    else:
                        usage["fetches"] += 1
                        result = web.call(tc.function.name, tc.function.arguments)
                    log(f"  {name} step {step + 1}: {tc.function.name}({(tc.function.arguments or '')[:120]})")
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            messages.append({"role": "user", "content": "Now publish the finished result as JSON. Use only facts and URLs you actually saw."})
        r = api.chat.completions.create(
            **common, messages=messages,
            response_format={"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}},
        )
        count(r)
        choice = r.choices[0]
        if choice.finish_reason == "length":
            raise RuntimeError(f"{name}: model hit max_tokens before finishing")
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", _strip_think(choice.message.content))
        result = json.loads(text)
    except Exception:
        on_usage and on_usage(usage, False)
        raise
    log(f"{name}: {usage['requests']} requests, {usage['input']:,} in / {usage['output']:,} out tokens ({model})")
    on_usage and on_usage(usage, True)
    return result, {"usage": usage, "seen_urls": seen_urls}


class LocalWeb:
    """Web search (DuckDuckGo) and page reading for local models, which have no server-side tools."""

    PAGE_CHARS = 3500
    TOOLS = [
        {"type": "function", "function": {
            "name": "web_search", "description": "Search the web. Returns titles, URLs and snippets.",
            "parameters": {"type": "object", "required": ["query"], "properties": {
                "query": {"type": "string"},
                "news": {"type": "boolean", "description": "Search recent news instead of the general web."},
            }},
        }},
        {"type": "function", "function": {
            "name": "fetch_page", "description": "Read the main text of a web page (first few thousand characters).",
            "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
        }},
    ]

    def __init__(self, seen_urls):
        self.seen_urls = seen_urls
        self.fetched = set()

    def call(self, fn, arguments):
        try:
            args = json.loads(arguments or "{}")
            return self.web_search(**args) if fn == "web_search" else self.fetch_page(**args)
        except Exception as e:
            return f"Error: {e}"

    def web_search(self, query, news=False):
        from ddgs import DDGS

        with DDGS() as d:
            results = list(d.news(query, max_results=6) if news else d.text(query, max_results=6))
        lines = []
        for r in results:
            url = r.get("href") or r.get("url")
            self.seen_urls.add(url)
            date = f" ({r['date'][:10]})" if r.get("date") else ""
            lines.append(f"- {r.get('title')}{date}\n  {url}\n  {(r.get('body') or '')[:300]}")
        return "\n".join(lines) or "No results."

    def fetch_page(self, url):
        import trafilatura

        if url in self.fetched:
            return "You already read this page above."
        self.fetched.add(url)
        html = trafilatura.fetch_url(url)
        if not html:
            return "Could not fetch that page."
        self.seen_urls.add(url)
        text = trafilatura.extract(html, include_links=False, include_tables=False) or ""
        return text[: self.PAGE_CHARS] or "Page had no readable text."
