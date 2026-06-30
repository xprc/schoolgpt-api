from typing import Literal

from langchain_core.tools import tool

from agent.tools.user_context import get_current_agent_user_id
from api.services.user_memory_service import get_user_memory_service
from api.services.user_service import get_user_service
from rag.rag_service import PolicyRagSearchService


policy_rag_search_service = PolicyRagSearchService()


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
