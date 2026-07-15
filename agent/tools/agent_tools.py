import json
from typing import Literal
from urllib.parse import urlparse

from langchain_core.tools import tool

from agent.tools.user_context import get_current_agent_user_id
from agent.tools.web_search_config_service import get_web_search_config_service
from agent.tools.user_memory_service import get_user_memory_service
from api.services.user_service import get_user_service
from rag.rag_service import PolicyRagSearchService


policy_rag_search_service = PolicyRagSearchService()
WEB_SEARCH_MAX_CONTENT_CHARS = 12000


def _json_response(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _truncate_text(text: object, limit: int = WEB_SEARCH_MAX_CONTENT_CHARS) -> str:
    content = str(text or "").strip()
    if len(content) <= limit:
        return content

    return content[:limit].rstrip() + "\n\n[内容已截断]"


def _preview_text(text: object, limit: int = 180) -> str:
    content = " ".join(str(text or "").split())
    if len(content) <= limit:
        return content

    return content[:limit].rstrip() + "..."


def _clamp_result_count(value: int) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = 5

    return max(1, min(count, 10))


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _markdown_label(value: object, fallback: str) -> str:
    label = str(value or "").strip() or fallback
    return label.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _markdown_url(value: object) -> str:
    return str(value or "").strip().replace(">", "%3E")


def _markdown_link(label: object, url: object, fallback: str) -> str:
    normalized_url = _markdown_url(url)
    if not normalized_url:
        return _markdown_label(label, fallback)

    return f"[{_markdown_label(label, fallback)}](<{normalized_url}>)"


def _source_title(title: object, url: object, source_id: int) -> str:
    normalized_title = str(title or "").strip()
    if normalized_title:
        return normalized_title

    parsed = urlparse(str(url or "").strip())
    if parsed.netloc:
        return parsed.netloc

    return f"来源 {source_id}"


def _source_markdown(source_id: int, title: str, url: str, description: str = "") -> str:
    line = f"{source_id}. {_markdown_link(title, url, f'来源 {source_id}')}"
    normalized_description = " ".join(str(description or "").split())
    if normalized_description:
        line += f" - {normalized_description}"

    return line


def _create_tavily_client():
    config = get_web_search_config_service().get_config()
    api_key = config.api_key.strip()

    if not config.is_enabled:
        return None, "联网搜索工具已在管理员中心停用。"

    if not api_key:
        return None, "请先在管理员中心的联网搜索配置中填写 Tavily API Key。"

    try:
        from tavily import TavilyClient
    except ImportError:
        return None, "后端未安装 tavily-python，请先安装依赖后再使用联网搜索。"

    return TavilyClient(api_key=api_key), ""


def _safe_tavily_error(error: Exception) -> str:
    return str(error).replace("\n", " ").strip() or error.__class__.__name__


def _format_search_result(result: object, source_id: int) -> dict[str, object]:
    if not isinstance(result, dict):
        return {
            "source_id": source_id,
            "content": str(result),
        }

    url = str(result.get("url") or "")
    title = _source_title(result.get("title"), url, source_id)
    content = _truncate_text(result.get("content"), 1200)
    description = _preview_text(result.get("content"))

    item: dict[str, object] = {
        "source_id": source_id,
        "title": title,
        "url": url,
        "citation": _markdown_link(str(source_id), url, str(source_id)),
        "source_markdown": _source_markdown(
            source_id,
            title,
            url,
            description,
        ),
        "content": content,
    }

    if result.get("score") is not None:
        item["score"] = result.get("score")
    if result.get("published_date"):
        item["published_date"] = result.get("published_date")
    if result.get("favicon"):
        item["favicon"] = result.get("favicon")

    return item


def _references_markdown(results: list[dict[str, object]]) -> str:
    references = [
        str(result["source_markdown"])
        for result in results
        if result.get("url") and result.get("source_markdown")
    ]
    if not references:
        return ""

    return "**来源**\n\n" + "\n".join(references)


@tool(
    "web_search",
    description=(
        "基于 Tavily 的联网搜索与网页查看工具。"
        "action=search 时必须提供 query，可返回标题、URL、摘要与相关度；"
        "action=view 时必须提供 url，可提取网页正文。"
        "仅用于公开网页信息，不用于学校本地政策库检索。"
    ),
)
def web_search(
    action: Literal["search", "view"],
    query: str = "",
    url: str = "",
    max_results: int = 5,
    search_depth: Literal["basic", "advanced", "fast", "ultra-fast"] = "basic",
    topic: Literal["general", "news", "finance"] = "general",
) -> str:
    client, error_message = _create_tavily_client()
    if client is None:
        return error_message

    normalized_action = str(action or "").strip().lower()
    normalized_query = query.strip()
    normalized_url = url.strip()

    if normalized_action == "search":
        if not normalized_query:
            return "联网搜索失败：必须提供 query。"

        result_count = _clamp_result_count(max_results)
        try:
            response = client.search(
                query=normalized_query,
                search_depth=search_depth,
                max_results=result_count,
                topic=topic,
                include_answer=True,
                include_raw_content=False,
                include_favicon=True,
            )
        except Exception as exc:
            return f"联网搜索失败：{_safe_tavily_error(exc)}"

        if not isinstance(response, dict):
            return _json_response(
                {
                    "query": normalized_query,
                    "results": [],
                    "raw_response": str(response),
                }
            )

        results = response.get("results")
        if not isinstance(results, list):
            results = []

        formatted_results = [
            _format_search_result(result, source_id)
            for source_id, result in enumerate(results[:result_count], 1)
        ]

        return _json_response(
            {
                "query": response.get("query") or normalized_query,
                "answer": response.get("answer") or "",
                "citation_usage": (
                    "最终回答引用联网信息时，在相关句子末尾使用 results[].citation "
                    "这样的 Markdown 链接；结尾添加 references_markdown 中的来源列表。"
                ),
                "results": formatted_results,
                "references_markdown": _references_markdown(formatted_results),
                "response_time": response.get("response_time"),
                "request_id": response.get("request_id"),
            }
        )

    if normalized_action == "view":
        if not normalized_url or not _is_http_url(normalized_url):
            return "查看网页失败：必须提供 http 或 https URL。"

        extract_kwargs: dict[str, object] = {
            "urls": normalized_url,
            "include_images": False,
            "include_favicon": True,
            "extract_depth": "basic",
            "format": "markdown",
            "timeout": 20.0,
        }
        if normalized_query:
            extract_kwargs["query"] = normalized_query
            extract_kwargs["chunks_per_source"] = 5

        try:
            response = client.extract(**extract_kwargs)
        except Exception as exc:
            return f"查看网页失败：{_safe_tavily_error(exc)}"

        if not isinstance(response, dict):
            return _json_response(
                {
                    "url": normalized_url,
                    "content": "",
                    "raw_response": str(response),
                }
            )

        results = response.get("results")
        if not isinstance(results, list):
            results = []

        first_result = results[0] if results else {}
        if not isinstance(first_result, dict):
            first_result = {}

        failed_results = response.get("failed_results")
        source_url = str(first_result.get("url") or normalized_url)
        title = _source_title("", source_url, 1)
        content = _truncate_text(first_result.get("raw_content"))
        formatted_result = {
            "source_id": 1,
            "title": title,
            "url": source_url,
            "citation": _markdown_link("1", source_url, "1"),
            "source_markdown": _source_markdown(
                1,
                title,
                source_url,
                _preview_text(first_result.get("raw_content")),
            ),
        }
        return _json_response(
            {
                "citation_usage": (
                    "最终回答引用该网页信息时，在相关句子末尾使用 citation "
                    "这个 Markdown 链接；结尾添加 references_markdown 中的来源列表。"
                ),
                "url": source_url,
                "citation": formatted_result["citation"],
                "content": content,
                "favicon": first_result.get("favicon") or "",
                "references_markdown": _references_markdown([formatted_result]),
                "failed_results": failed_results if isinstance(failed_results, list) else [],
                "response_time": response.get("response_time"),
                "request_id": response.get("request_id"),
            }
        )

    return "不支持的 action。请使用 search 或 view。"


@tool(
    "policy_rag_search",
    description="从学校政策向量库检索参考资料，并返回可用于回答用户问题的政策内容摘要。",
)
def policy_rag_search(query: str) -> str:
    return policy_rag_search_service.policy_rag_search(query)


@tool(
    "user_memory",
    description=(
        "增删改查当前登录用户的长期文本记忆。"
        "action 必须是 list、search、read、create、save、update 或 delete。"
        "list/search/read 用于查询；create/save 用 text 新增记忆；"
        "update 用 memory_id 和 text 修改已有记忆；delete 用 memory_id 删除已有记忆。"
        "只能操作当前用户自己的记忆，只保存用户明确表达、长期有用且不敏感的信息。"
    ),
)
def user_memory(
    action: Literal["list", "search", "read", "create", "save", "update", "delete"],
    query: str = "",
    memory_id: str = "",
    text: str = "",
) -> str:
    user_id = get_current_agent_user_id()
    if user_id is None:
        return "当前会话没有可用的用户身份，无法读取或保存用户记忆。"

    memory_service = get_user_memory_service()
    user = get_user_service().get_user_by_id(user_id)
    if user is not None and user.is_active:
        memory_service.ensure_default_identity_memory(user_id, user.user_type)

    normalized_action = str(action or "").strip().lower()

    if normalized_action in {"list", "search", "read"}:
        normalized_memory_id = memory_id.strip()
        if normalized_memory_id:
            try:
                memory = memory_service.get_memory(
                    user_id=user_id,
                    memory_id=normalized_memory_id,
                )
            except ValueError:
                return "读取用户记忆失败：memory_id 格式不正确。"

            if memory is None:
                return "读取用户记忆失败：记忆不存在或无权访问。"

            return memory_service.format_memories_for_agent([memory])

        memories = memory_service.list_memories(
            user_id=user_id,
            query=query,
            limit=8,
            fallback_to_recent=True,
        )
        return memory_service.format_memories_for_agent(memories)

    if normalized_action in {"create", "save"}:
        try:
            memory = memory_service.create_memory(user_id=user_id, content=text)
        except ValueError as exc:
            return f"保存用户记忆失败：{exc}"

        return (
            "已新增用户记忆："
            f"id={memory.id} | content={memory.content}"
        )

    if normalized_action == "update":
        normalized_memory_id = memory_id.strip()
        if not normalized_memory_id:
            return "修改用户记忆失败：必须提供 memory_id。"

        try:
            memory = memory_service.update_memory(
                user_id=user_id,
                memory_id=normalized_memory_id,
                content=text,
            )
        except ValueError as exc:
            return f"修改用户记忆失败：{exc}"

        if memory is None:
            return "修改用户记忆失败：记忆不存在或无权访问。"

        return (
            "已修改用户记忆："
            f"id={memory.id} | content={memory.content}"
        )

    if normalized_action == "delete":
        normalized_memory_id = memory_id.strip()
        if not normalized_memory_id:
            return "删除用户记忆失败：必须提供 memory_id。"

        try:
            deleted = memory_service.delete_memory(
                user_id=user_id,
                memory_id=normalized_memory_id,
            )
        except ValueError:
            return "删除用户记忆失败：memory_id 格式不正确。"

        if not deleted:
            return "删除用户记忆失败：记忆不存在或无权访问。"

        return f"已删除用户记忆：id={normalized_memory_id}"

    return "不支持的 action。请使用 list、search、read、create、save、update 或 delete。"
