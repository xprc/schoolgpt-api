import asyncio
import json
from collections.abc import AsyncIterator
from functools import lru_cache

from api.services.model_config_service import ModelConfigService, get_model_config_service
from model.factory import ModelConfigurationError, create_webchat_model


class ChatService:
    def __init__(self, model_config_service: ModelConfigService) -> None:
        from agent.react_agent import ReactAgent

        self._agent_class = ReactAgent
        self._model_config_service = model_config_service
        self._agent = None
        self._agent_cache_key: str | None = None

    def _get_agent(self):
        model_config = self._model_config_service.get_active_model_config()
        if not model_config.api_key.strip():
            raise ModelConfigurationError("请先在管理员中心配置模型 API Key")

        if self._agent is None or self._agent_cache_key != model_config.cache_key:
            self._agent = self._agent_class(create_webchat_model(model_config))
            self._agent_cache_key = model_config.cache_key

        return self._agent

    def ensure_ready(self) -> None:
        self._get_agent()

    async def stream_response(
        self,
        query: str,
        delay_seconds: float,
    ) -> AsyncIterator[str]:
        async for char in self.stream_content(query, delay_seconds):
            yield f"data: {json.dumps(char, ensure_ascii=False)}\n\n"

        yield "data: [DONE]\n\n"

    async def stream_content(
        self,
        query: str,
        delay_seconds: float,
    ) -> AsyncIterator[str]:
        agent = self._get_agent()
        for chunk in agent.execute_stream(query):
            for char in chunk:
                if delay_seconds > 0:
                    await asyncio.sleep(delay_seconds)
                yield char


@lru_cache(maxsize=1)
def get_chat_service() -> ChatService:
    return ChatService(get_model_config_service())
