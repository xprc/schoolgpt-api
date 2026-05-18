from langchain.agents import create_agent
from agent.tools.middleware import monitor_tool, log_before_model, report_prompt_switch
from agent.tools.agent_tools import rag_summarize
from model.factory import webchat_model
from utils.prompt_loader import load_system_prompt


class ReactAgent(object):
    def __init__(self):
        self.agent = create_agent(
            model=webchat_model,
            system_prompt=load_system_prompt(),
            tools=[rag_summarize],
            middleware=[monitor_tool, log_before_model, report_prompt_switch],
        )

    def execute_stream(self, query):
        input_dict = {
            "messages": [
                {"role": "user", "content": query},
            ]
        }

        for chunk in self.agent.stream(input_dict, stream_mode="values", context={"report": False}):
            latest_message = chunk["messages"][-1]  # 有历史记录所以取最后一条
            if latest_message.content:
                yield latest_message.content.strip() + "\n"

if __name__ == '__main__':
    ang=ReactAgent()
    result = ang.execute_stream("如何转专业")
    for chunk in result:
        print(chunk, end="", flush=True)  # 模拟流式打字机效果