from langchain_core.tools import tool

from rag.rag_service import RagSummarylize


rag = RagSummarylize()


@tool(description="从向量存储中检索参考资料")
def rag_summarize(query: str) -> str:
    return rag.rag_summarize(query)
