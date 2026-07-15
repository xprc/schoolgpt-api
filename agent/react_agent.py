import json

from langchain.agents import create_agent
from agent.tools.middleware import monitor_tool, log_before_model, report_prompt_switch
from agent.tools.agent_tools import policy_rag_search, user_memory, web_search
from agent.tools.user_context import (
    reset_current_agent_user_id,
    set_current_agent_user_id,
)
from model.factory import create_webchat_model
from prompts.prompt_loader import load_system_prompt


class ReactAgent(object):
    def __init__(self, model=None):
        self.agent = create_agent(
            model=model or create_webchat_model(),
            system_prompt=load_system_prompt(),
            tools=[policy_rag_search, user_memory, web_search],
            middleware=[monitor_tool, log_before_model, report_prompt_switch],
        )

    @staticmethod
    def _message_role(message):
        if isinstance(message, dict):
            return message.get("role") or message.get("type")

        return getattr(message, "type", None) or getattr(message, "role", None)

    @classmethod
    def _is_ai_message(cls, message):
        role = cls._message_role(message)
        if isinstance(role, str) and role.lower() in {
            "ai",
            "assistant",
            "aimessage",
            "aimessagechunk",
        }:
            return True

        class_name = message.__class__.__name__.lower()
        return class_name.startswith("ai")

    @staticmethod
    def _message_content(message):
        if isinstance(message, dict):
            content = message.get("content")
        else:
            content = getattr(message, "content", "")

        if isinstance(content, str):
            return content

        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    item_type = str(item.get("type") or "").lower()
                    if "reasoning" in item_type or "tool" in item_type:
                        continue

                    text = item.get("text") or item.get("content")
                    if isinstance(text, str):
                        parts.append(text)

            return "".join(parts)

        return str(content) if content else ""

    @staticmethod
    def _preview_text(text, limit=500):
        text = str(text or "").strip()
        if len(text) <= limit:
            return text

        return text[:limit].rstrip() + "..."

    @classmethod
    def _is_tool_message(cls, message):
        role = cls._message_role(message)
        if isinstance(role, str) and role.lower() in {"tool", "toolmessage"}:
            return True

        class_name = message.__class__.__name__.lower()
        return class_name.startswith("tool")

    @staticmethod
    def _as_list(value):
        if not value:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)

        return [value]

    @staticmethod
    def _tool_call_value(tool_call, key):
        if isinstance(tool_call, dict):
            return tool_call.get(key)

        return getattr(tool_call, key, None)

    @classmethod
    def _stringify_tool_args(cls, args):
        if args is None:
            return ""
        if isinstance(args, str):
            return args.strip()

        try:
            return json.dumps(args, ensure_ascii=False)
        except TypeError:
            return str(args)

    @classmethod
    def _tool_call_info(cls, tool_call):
        name = cls._tool_call_value(tool_call, "name")
        args = cls._tool_call_value(tool_call, "args")
        call_id = cls._tool_call_value(tool_call, "id")
        index = cls._tool_call_value(tool_call, "index")
        function = cls._tool_call_value(tool_call, "function")

        if function:
            if isinstance(function, dict):
                name = name or function.get("name")
                args = args if args is not None else function.get("arguments")
            else:
                name = name or getattr(function, "name", None)
                if args is None:
                    args = getattr(function, "arguments", None)

        return {
            "id": str(call_id or ""),
            "index": index,
            "name": str(name or ""),
            "args": cls._stringify_tool_args(args),
        }

    @classmethod
    def _message_tool_call_infos(cls, message, field_name):
        values = []
        if isinstance(message, dict):
            values.extend(cls._as_list(message.get(field_name)))
            additional_kwargs = message.get("additional_kwargs")
            if isinstance(additional_kwargs, dict):
                values.extend(cls._as_list(additional_kwargs.get(field_name)))
        else:
            values.extend(cls._as_list(getattr(message, field_name, None)))
            additional_kwargs = getattr(message, "additional_kwargs", None)
            if isinstance(additional_kwargs, dict):
                values.extend(cls._as_list(additional_kwargs.get(field_name)))

        return [cls._tool_call_info(value) for value in values]

    @classmethod
    def _format_tool_calls(cls, tool_calls):
        lines = []
        for tool_call in tool_calls:
            name = tool_call.get("name") or "unknown"
            args = cls._preview_text(tool_call.get("args") or "", 300)
            line = f"[Agent] 调用工具 {name}"
            if args:
                line += f"：{args}"
            lines.append(line)

        return "\n".join(lines) + ("\n" if lines else "")

    @classmethod
    def _merge_tool_call_chunks(cls, pending_tool_calls, tool_call_chunks):
        for position, tool_call in enumerate(tool_call_chunks):
            index = tool_call.get("index")
            key = index if index is not None else tool_call.get("id") or position
            pending_tool_call = pending_tool_calls.setdefault(
                key,
                {
                    "id": "",
                    "index": index,
                    "name": "",
                    "args": "",
                },
            )
            if tool_call.get("id"):
                pending_tool_call["id"] = tool_call["id"]
            if tool_call.get("name"):
                pending_tool_call["name"] = tool_call["name"]
            if tool_call.get("args"):
                pending_tool_call["args"] += tool_call["args"]

    @classmethod
    def _tool_message_text(cls, message):
        if isinstance(message, dict):
            name = message.get("name") or message.get("tool_name")
            tool_call_id = message.get("tool_call_id")
        else:
            name = getattr(message, "name", None) or getattr(message, "tool_name", None)
            tool_call_id = getattr(message, "tool_call_id", None)

        label = name or tool_call_id or "unknown"
        content = cls._preview_text(cls._message_content(message))
        if content:
            return f"[Agent] 工具返回 {label}：{content}\n"

        return f"[Agent] 工具返回 {label}\n"

    @staticmethod
    def _message_reasoning_content(message):
        candidates = []
        if isinstance(message, dict):
            candidates.append(message)
            additional_kwargs = message.get("additional_kwargs")
            response_metadata = message.get("response_metadata")
            content = message.get("content")
        else:
            candidates.append(message)
            additional_kwargs = getattr(message, "additional_kwargs", None)
            response_metadata = getattr(message, "response_metadata", None)
            content = getattr(message, "content", None)

        if isinstance(additional_kwargs, dict):
            candidates.append(additional_kwargs)
        if isinstance(response_metadata, dict):
            candidates.append(response_metadata)
        if isinstance(content, dict):
            candidates.append(content)
        if isinstance(content, list):
            candidates.extend(item for item in content if isinstance(item, dict))

        for candidate in candidates:
            if isinstance(candidate, dict):
                reasoning_content = (
                    candidate.get("reasoning_content")
                    or candidate.get("reasoning")
                    or candidate.get("reasoning_text")
                )
                candidate_type = str(candidate.get("type") or "").lower()
                if not reasoning_content and "reasoning" in candidate_type:
                    reasoning_content = candidate.get("text") or candidate.get("content")

                delta = candidate.get("delta")
                if not reasoning_content and isinstance(delta, dict):
                    reasoning_content = delta.get("reasoning_content")

                if isinstance(reasoning_content, dict):
                    reasoning_content = (
                        reasoning_content.get("text")
                        or reasoning_content.get("content")
                    )
            else:
                reasoning_content = getattr(candidate, "reasoning_content", None)

            if isinstance(reasoning_content, str):
                return reasoning_content

        return ""

    @staticmethod
    def _has_tool_calls(message):
        if isinstance(message, dict):
            additional_kwargs = message.get("additional_kwargs")
            return bool(
                message.get("tool_calls")
                or message.get("tool_call_chunks")
                or (
                    isinstance(additional_kwargs, dict)
                    and additional_kwargs.get("tool_calls")
                )
            )

        return bool(
            getattr(message, "tool_calls", None)
            or getattr(message, "tool_call_chunks", None)
        )

    @staticmethod
    def _message_id(message):
        if isinstance(message, dict):
            return message.get("id")

        return getattr(message, "id", None)

    @staticmethod
    def _message_finish_reason(message):
        candidates = []
        if isinstance(message, dict):
            candidates.append(message)
            response_metadata = message.get("response_metadata")
            generation_info = message.get("generation_info")
        else:
            candidates.append(message)
            response_metadata = getattr(message, "response_metadata", None)
            generation_info = getattr(message, "generation_info", None)

        if isinstance(response_metadata, dict):
            candidates.append(response_metadata)
        if isinstance(generation_info, dict):
            candidates.append(generation_info)

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue

            finish_reason = (
                candidate.get("finish_reason")
                or candidate.get("finishReason")
                or candidate.get("stop_reason")
            )
            if isinstance(finish_reason, str):
                return finish_reason

        return None

    @staticmethod
    def _stream_item_message(stream_item):
        if isinstance(stream_item, tuple) and stream_item:
            return stream_item[0]

        if isinstance(stream_item, dict):
            for key in ("message", "chunk"):
                value = stream_item.get(key)
                if value is not None:
                    return value

        return stream_item

    @staticmethod
    def _agent_context(
        user_id: int | None,
        user_runtime_context: str | None = None,
    ) -> dict[str, object]:
        context: dict[str, object] = {"report": False}
        if user_id is not None:
            context["user_id"] = user_id

        normalized_context = str(user_runtime_context or "").strip()
        if normalized_context:
            context["user_runtime_context"] = normalized_context

        return context

    def _execute_messages_stream(
        self,
        input_dict,
        user_id: int | None = None,
        user_runtime_context: str | None = None,
    ):
        pending_message_id = None
        pending_content = ""
        pending_has_tool_call = False
        pending_tool_calls = {}
        reported_tool_call_texts = set()
        reported_tool_message_keys = set()

        for stream_item in self.agent.stream(
            input_dict,
            stream_mode="messages",
            context=self._agent_context(user_id, user_runtime_context),
        ):
            latest_message = self._stream_item_message(stream_item)
            if self._is_tool_message(latest_message):
                tool_message_text = self._tool_message_text(latest_message)
                tool_message_key = self._message_id(latest_message) or tool_message_text
                if tool_message_key not in reported_tool_message_keys:
                    reported_tool_message_keys.add(tool_message_key)
                    yield {
                        "type": "reasoning",
                        "content": tool_message_text,
                    }
                continue

            if not self._is_ai_message(latest_message):
                continue

            message_id = self._message_id(latest_message)
            if message_id is not None and message_id != pending_message_id:
                pending_message_id = message_id
                pending_content = ""
                pending_has_tool_call = False
                pending_tool_calls = {}

            reasoning_content = self._message_reasoning_content(latest_message)
            if reasoning_content:
                yield {
                    "type": "reasoning",
                    "content": reasoning_content,
                }

            full_tool_calls = self._message_tool_call_infos(latest_message, "tool_calls")
            if full_tool_calls:
                pending_has_tool_call = True
                tool_call_text = self._format_tool_calls(full_tool_calls)
                if tool_call_text and tool_call_text not in reported_tool_call_texts:
                    reported_tool_call_texts.add(tool_call_text)
                    yield {
                        "type": "reasoning",
                        "content": tool_call_text,
                    }

            tool_call_chunks = self._message_tool_call_infos(
                latest_message,
                "tool_call_chunks",
            )
            if tool_call_chunks:
                pending_has_tool_call = True
                self._merge_tool_call_chunks(pending_tool_calls, tool_call_chunks)

            content = self._message_content(latest_message)
            if content:
                pending_content += content

            finish_reason = self._message_finish_reason(latest_message)
            if finish_reason is None:
                continue

            if finish_reason == "tool_calls" and pending_tool_calls:
                tool_call_text = self._format_tool_calls(pending_tool_calls.values())
                if tool_call_text and tool_call_text not in reported_tool_call_texts:
                    reported_tool_call_texts.add(tool_call_text)
                    yield {
                        "type": "reasoning",
                        "content": tool_call_text,
                    }

            if finish_reason == "stop" and pending_content and not pending_has_tool_call:
                yield {
                    "type": "content",
                    "content": pending_content,
                }

            pending_content = ""
            pending_has_tool_call = False
            pending_tool_calls = {}

    def _execute_values_stream(
        self,
        input_dict,
        user_id: int | None = None,
        user_runtime_context: str | None = None,
    ):
        streamed_content = ""
        streamed_reasoning_content = ""
        reported_tool_call_texts = set()
        reported_tool_message_keys = set()
        for chunk in self.agent.stream(
            input_dict,
            stream_mode="values",
            context=self._agent_context(user_id, user_runtime_context),
        ):
            messages = chunk.get("messages", [])
            if not messages:
                continue

            latest_message = messages[-1]
            if self._is_tool_message(latest_message):
                tool_message_text = self._tool_message_text(latest_message)
                tool_message_key = self._message_id(latest_message) or tool_message_text
                if tool_message_key not in reported_tool_message_keys:
                    reported_tool_message_keys.add(tool_message_key)
                    yield {
                        "type": "reasoning",
                        "content": tool_message_text,
                    }
                continue

            if not self._is_ai_message(latest_message):
                continue
            if self._has_tool_calls(latest_message):
                tool_calls = self._message_tool_call_infos(latest_message, "tool_calls")
                if not tool_calls:
                    tool_calls = self._message_tool_call_infos(
                        latest_message,
                        "tool_call_chunks",
                    )

                tool_call_text = self._format_tool_calls(tool_calls)
                if tool_call_text and tool_call_text not in reported_tool_call_texts:
                    reported_tool_call_texts.add(tool_call_text)
                    yield {
                        "type": "reasoning",
                        "content": tool_call_text,
                    }
                continue

            reasoning_content = self._message_reasoning_content(latest_message)
            if reasoning_content:
                if reasoning_content.startswith(streamed_reasoning_content):
                    reasoning_delta = reasoning_content[len(streamed_reasoning_content):]
                else:
                    reasoning_delta = reasoning_content

                if reasoning_delta:
                    streamed_reasoning_content = reasoning_content
                    yield {
                        "type": "reasoning",
                        "content": reasoning_delta,
                    }

            content = self._message_content(latest_message)
            if not content:
                continue

            if content.startswith(streamed_content):
                delta = content[len(streamed_content):]
            else:
                delta = content

            if not delta:
                continue

            streamed_content = content
            yield {
                "type": "content",
                "content": delta,
            }

    def execute_stream(
        self,
        messages,
        user_id: int | None = None,
        user_runtime_context: str | None = None,
    ):
        if isinstance(messages, str):
            input_messages = [{"role": "user", "content": messages}]
        else:
            input_messages = messages

        input_dict = {"messages": input_messages}
        emitted_any = False
        user_context_token = set_current_agent_user_id(user_id)
        try:
            for event in self._execute_messages_stream(
                input_dict,
                user_id,
                user_runtime_context,
            ):
                emitted_any = True
                yield event
        except Exception:
            if emitted_any:
                raise

            yield from self._execute_values_stream(
                input_dict,
                user_id,
                user_runtime_context,
            )
        finally:
            reset_current_agent_user_id(user_context_token)
