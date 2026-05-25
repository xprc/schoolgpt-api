import asyncio
from collections.abc import AsyncIterator
from functools import lru_cache


class ChatService:
    def __init__(self) -> None:
        from agent.react_agent import ReactAgent

        self._agent = ReactAgent()

    async def stream_response(
        self,
        query: str,
        delay_seconds: float,
    ) -> AsyncIterator[str]:
        for chunk in self._agent.execute_stream(query):
            for char in chunk:
                if delay_seconds > 0:
                    await asyncio.sleep(delay_seconds)
                yield f"data: {char}\n\n"

        yield "data: [DONE]\n\n"


@lru_cache(maxsize=1)
def get_chat_service() -> ChatService:
    return ChatService()
