import asyncio
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from functools import lru_cache

from api.services.model_config_service import ModelConfigService, get_model_config_service
from api.services.model_config_service import ModelConfig
from model.factory import ModelConfigurationError, create_webchat_model
from rag.source_context import get_rag_sources, reset_rag_sources, restore_rag_sources
from utils.prompt_loader import load_system_prompt


class ChatService:
    def __init__(self, model_config_service: ModelConfigService) -> None:
        from agent.react_agent import ReactAgent

        self._agent_class = ReactAgent
        self._model_config_service = model_config_service
        self._agents: dict[str, object] = {}
        self._agent_config_cache_key: str | None = None

    def _get_active_model_config(self) -> ModelConfig:
        model_config = self._model_config_service.get_active_model_config()
        if not model_config.api_key.strip():
            raise ModelConfigurationError("请先在管理员中心配置模型 API Key")

        return model_config

    def _get_agent(self, enable_thinking: bool = True):
        model_config = self._get_active_model_config()

        if self._agent_config_cache_key != model_config.cache_key:
            self._agents = {}
            self._agent_config_cache_key = model_config.cache_key

        agent_cache_key = f"{model_config.cache_key}:thinking={enable_thinking}"
        if agent_cache_key not in self._agents:
            try:
                self._agents[agent_cache_key] = self._agent_class(
                    create_webchat_model(
                        model_config,
                        enable_thinking=enable_thinking,
                    )
                )
            except ModelConfigurationError:
                raise
            except Exception as exc:
                raise ModelConfigurationError(f"模型初始化失败: {exc}") from exc

        return self._agents[agent_cache_key]

    def ensure_ready(self, enable_thinking: bool = True) -> None:
        self._get_agent(enable_thinking)

    @staticmethod
    def _message_text(messages: Sequence[Mapping[str, str]] | str) -> str:
        if isinstance(messages, str):
            return messages

        for message in reversed(messages):
            if message.get("role") == "user":
                return str(message.get("content") or "")

        return ""

    @staticmethod
    def _to_openai_messages(messages: Sequence[Mapping[str, str]] | str) -> list[dict[str, str]]:
        if isinstance(messages, str):
            return [{"role": "user", "content": messages}]

        openai_messages = []
        for message in messages:
            role = message.get("role")
            content = str(message.get("content") or "").strip()
            if role not in {"user", "assistant"} or not content:
                continue

            openai_messages.append(
                {
                    "role": role,
                    "content": content,
                }
            )

        return openai_messages

    @staticmethod
    def _build_rag_context(query: str) -> str:
        if not query.strip():
            return ""

        from agent.tools.agent_tools import policy_rag_search_service
        from rag.source_context import add_rag_sources

        context_docs = policy_rag_search_service.retriever_docs(query)
        add_rag_sources(
            [
                {
                    "file_name": item["file_name"],
                    "confidence": item["confidence"],
                }
                for item in context_docs
            ]
        )

        context_parts = []
        for counter, item in enumerate(context_docs, 1):
            doc = item["document"]
            context_parts.append(
                "[reference {counter}] confidence: {confidence:.4f} | "
                "content: {content} | metadata: {metadata}".format(
                    counter=counter,
                    confidence=item["confidence"],
                    content=doc.page_content,
                    metadata=doc.metadata,
                )
            )

        return "\n".join(context_parts)

    def _stream_deepseek_events(
        self,
        model_config: ModelConfig,
        messages: Sequence[Mapping[str, str]] | str,
    ):
        from openai import OpenAI

        query = self._message_text(messages)
        rag_context = self._build_rag_context(query)
        openai_messages = [
            {
                "role": "system",
                "content": load_system_prompt(),
            }
        ]
        if rag_context:
            openai_messages.append(
                {
                    "role": "system",
                    "content": (
                        "以下是从学校政策知识库检索到的参考资料。回答用户时优先依据这些资料；"
                        "资料不足时请明确说明。\n\n"
                        f"{rag_context}"
                    ),
                }
            )
        openai_messages.extend(self._to_openai_messages(messages))

        client = OpenAI(
            api_key=model_config.api_key,
            base_url=model_config.base_url,
        )
        stream = client.chat.completions.create(
            model=model_config.model_name,
            messages=openai_messages,
            stream=True,
            reasoning_effort="high",
            extra_body={
                "thinking": {
                    "type": "enabled",
                },
            },
        )

        for chunk in stream:
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta
            reasoning_content = getattr(delta, "reasoning_content", None)
            if reasoning_content:
                yield {
                    "type": "reasoning",
                    "content": reasoning_content,
                }

            content = getattr(delta, "content", None)
            if content:
                yield {
                    "type": "content",
                    "content": content,
                }

    async def stream_response(
        self,
        query: str,
        delay_seconds: float,
        enable_thinking: bool = True,
    ) -> AsyncIterator[str]:
        rag_token = reset_rag_sources()
        try:
            async for event in self.stream_events(
                [{"role": "user", "content": query}],
                delay_seconds,
                enable_thinking,
            ):
                payload: object = event["content"]
                if event["type"] != "content":
                    payload = event

                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            rag_sources = get_rag_sources()
            if rag_sources:
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "type": "rag_sources",
                            "sources": rag_sources,
                        },
                        ensure_ascii=False,
                    )
                    + "\n\n"
                )

            yield "data: [DONE]\n\n"
        finally:
            restore_rag_sources(rag_token)

    async def stream_content(
        self,
        messages: Sequence[Mapping[str, str]] | str,
        delay_seconds: float,
        enable_thinking: bool = True,
    ) -> AsyncIterator[str]:
        async for event in self.stream_events(
            messages,
            delay_seconds,
            enable_thinking,
        ):
            if event["type"] == "content":
                yield event["content"]

    async def stream_events(
        self,
        messages: Sequence[Mapping[str, str]] | str,
        delay_seconds: float,
        enable_thinking: bool = True,
    ) -> AsyncIterator[dict[str, str]]:
        agent = self._get_agent(enable_thinking)
        chunks = agent.execute_stream(messages)
        pending_reasoning_parts: list[str] = []
        saw_content = False

        async def emit_text(event_type: str, text: str) -> AsyncIterator[dict[str, str]]:
            for char in text:
                if delay_seconds > 0:
                    await asyncio.sleep(delay_seconds)
                yield {
                    "type": event_type,
                    "content": char,
                }

        async def flush_pending_reasoning(
            event_type: str,
        ) -> AsyncIterator[dict[str, str]]:
            if not pending_reasoning_parts:
                return

            pending_text = "".join(pending_reasoning_parts)
            pending_reasoning_parts.clear()
            async for event in emit_text(event_type, pending_text):
                yield event

        for chunk in chunks:
            if isinstance(chunk, str):
                event_type = "content"
                content = chunk
            else:
                event_type = str(chunk.get("type") or "content")
                content = str(chunk.get("content") or "")

            if event_type not in {"content", "reasoning"} or not content:
                continue

            if event_type == "reasoning":
                is_agent_trace = content.startswith("[Agent]")
                if is_agent_trace:
                    async for event in flush_pending_reasoning("reasoning"):
                        yield event
                    async for event in emit_text("reasoning", content):
                        yield event
                elif saw_content:
                    async for event in emit_text("reasoning", content):
                        yield event
                else:
                    pending_reasoning_parts.append(content)
                continue

            async for event in flush_pending_reasoning("reasoning"):
                yield event
            saw_content = True
            async for event in emit_text("content", content):
                yield event

        if pending_reasoning_parts:
            async for event in flush_pending_reasoning("content"):
                yield event


@lru_cache(maxsize=1)
def get_chat_service() -> ChatService:
    return ChatService(get_model_config_service())
