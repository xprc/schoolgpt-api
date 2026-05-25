from typing import Callable, Any
from langchain.agents import AgentState
from langchain.agents.middleware import wrap_tool_call, before_model, dynamic_prompt, ModelRequest
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.runtime import Runtime
from langgraph.types import Command
from utils.logger_handler import logger
from utils.prompt_loader import load_system_prompt, load_report_prompt


@wrap_tool_call
def monitor_tool(
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command]
) -> ToolMessage | Command:
    tool_name = request.tool_call["name"]
    logger.info("[tool monitor]执行工具: %s", tool_name)
    try:
        result = handler(request)
        logger.info("[tool monitor]工具调用成功: %s", tool_name)

        if tool_name == "fill_context_for_report":
            logger.info("[tool monitor]报告上下文已启用")
            request.runtime.context["report"] = True
        return result
    except Exception as e:
        logger.error("工具调用失败: %s | %s", tool_name, e)
        raise


@before_model
def log_before_model(state: AgentState, _runtime: Runtime) -> dict[str, Any] | None:
    logger.info("[model]即将调用模型，消息数量: %s", len(state["messages"]))
    return None


@dynamic_prompt
def report_prompt_switch(request: ModelRequest) -> str:
    is_report = request.runtime.context.get("report", False)
    if is_report:
        return load_report_prompt()

    return load_system_prompt()
