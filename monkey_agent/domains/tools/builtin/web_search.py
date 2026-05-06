from __future__ import annotations

import html
import re
import ssl
import urllib.parse
import urllib.request
from typing import Any

from monkey_agent.domains.tools.capability import ToolResult
from monkey_agent.domains.tools import Permission, ToolRisk, ToolSchema


class WebSearchTool:
    id = "public_web_search"
    name = "公开网络搜索"
    description = "通过公开搜索页面检索网页标题、摘要和链接，用于回答公开信息类问题或支撑 Skill 沉淀。"
    input_schema = ToolSchema(
        required=[],
        properties={"query": "可选；缺省时使用用户问题"},
    )
    output_schema = ToolSchema(
        required=["content"],
        properties={"content": "搜索摘要", "data.results": "搜索结果列表"},
    )
    permission = Permission.AUTO
    risk = ToolRisk.LOW
    read_only = True
    learn_policy = "skill"

    def can_handle(self, question: str, context: dict[str, Any]) -> bool:
        if context.get("capability") == "web_search":
            return True
        hints = (
            "搜索",
            "网上",
            "公开",
            "文档",
            "资料",
            "怎么",
            "如何",
            "是什么",
            "查一下",
            "查询",
            "最新",
            "比赛",
            "赛程",
            "NBA",
            "球队",
            "赛事",
        )
        return any(hint in question for hint in hints)

    def execute(self, question: str, context: dict[str, Any]) -> ToolResult:
        query = str(context.get("query") or question)
        try:
            results = _search(query)
        except Exception as exc:  # noqa: BLE001 - network boundary
            return ToolResult(
                tool_id=self.id,
                tool_name=self.name,
                success=False,
                stable_rule_candidate=False,
                candidate_type="skill",
                content=f"网络搜索失败：{exc}",
                error=str(exc),
                permission=self.permission,
                risk=self.risk,
                read_only=self.read_only,
            )
        if not results:
            return ToolResult(
                tool_id=self.id,
                tool_name=self.name,
                success=False,
                stable_rule_candidate=False,
                candidate_type="skill",
                content="未搜索到可用公开结果。",
                error="no_results",
                permission=self.permission,
                risk=self.risk,
                read_only=self.read_only,
            )
        summary = "\n".join(
            f"- {item['title']}: {item['snippet']} ({item['url']})"
            for item in results[:5]
        )
        return ToolResult(
            tool_id=self.id,
            tool_name=self.name,
            success=True,
            stable_rule_candidate=False,
            candidate_type="skill",
            content=f"已通过公开网络搜索找到可参考信息：\n{summary}",
            data={
                "query": query,
                "results": results[:5],
                "public_support": True,
            },
            public_evidence=results[:5],
            permission=self.permission,
            risk=self.risk,
            read_only=self.read_only,
        )


def _search(query: str) -> list[dict[str, str]]:
    params = urllib.parse.urlencode({"q": query})
    url = f"https://duckduckgo.com/html/?{params}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 MonkeyAgent/0.1"},
    )
    with urllib.request.urlopen(request, timeout=10, context=_ssl_context()) as response:
        body = response.read().decode("utf-8", errors="replace")
    return _parse_duckduckgo_html(body)


def _parse_duckduckgo_html(body: str) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    blocks = re.findall(r'<div class="result.*?</div>\s*</div>', body, flags=re.S)
    if not blocks:
        blocks = body.split('class="result__body"')
    for block in blocks:
        title_match = re.search(
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            block,
            flags=re.S,
        )
        if not title_match:
            continue
        raw_url = html.unescape(title_match.group(1))
        title = _clean_html(title_match.group(2))
        snippet_match = re.search(
            r'class="result__snippet"[^>]*>(.*?)</a>|class="result__snippet"[^>]*>(.*?)</div>',
            block,
            flags=re.S,
        )
        snippet = ""
        if snippet_match:
            snippet = _clean_html(snippet_match.group(1) or snippet_match.group(2) or "")
        results.append(
            {
                "title": title,
                "url": _normalize_duckduckgo_url(raw_url),
                "snippet": snippet,
            }
        )
    return results[:10]


def _normalize_duckduckgo_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    if "uddg" in qs and qs["uddg"]:
        return qs["uddg"][0]
    return url


def _clean_html(value: str) -> str:
    value = re.sub(r"<.*?>", "", value, flags=re.S)
    return html.unescape(value).strip()


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())
