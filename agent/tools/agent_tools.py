from langchain_core.tools import tool

from rag.rag_service import PolicyRagSearchService


policy_rag_search_service = PolicyRagSearchService()


@tool(
    "policy_rag_search",
    description="从学校政策向量库检索参考资料，并返回可用于回答用户问题的政策内容摘要。",
)
def policy_rag_search(query: str) -> str:
    return policy_rag_search_service.policy_rag_search(query)
