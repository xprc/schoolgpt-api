from langchain_core.tools import tool
from langgraph.prebuilt.tool_node import ToolCallRequest

from rag.vector_store import VectorStoreService
from rag.rag_service import RagSummarylize
import random, os
from utils.config_handler import agent_conf
from utils.path_tools import get_abs_path
from utils.logger_handler import logger


vector_store = VectorStoreService()
rag = RagSummarylize()

external_data = {}

@tool(description="从向量存储中检索参考资料")
def rag_summarize(query: str) -> str:
    return rag.rag_summarize(query)


