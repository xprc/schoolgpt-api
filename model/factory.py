from abc import ABC,abstractmethod
from pathlib import Path

from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_community.embeddings import HuggingFaceBgeEmbeddings

from api.services.model_config_service import ModelConfig, get_model_config_service
from utils.config_handler import rag_conf
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI


class ModelConfigurationError(Exception):
    pass

class BaseModelFactory(ABC):

    @abstractmethod
    def generator(self):
        pass


def _thinking_extra_body(
    model_config: ModelConfig,
    enable_thinking: bool,
) -> dict[str, object] | None:
    if (
        model_config.provider == "deepseek"
        and model_config.model_name.lower().startswith("deepseek-v4")
    ):
        return {
            "thinking": {
                "type": "enabled" if enable_thinking else "disabled",
            },
        }

    return None


def _model_fields(model_class: type) -> dict[str, object]:
    fields = getattr(model_class, "model_fields", None)
    if isinstance(fields, dict):
        return fields

    fields = getattr(model_class, "__fields__", None)
    if isinstance(fields, dict):
        return fields

    return {}


def _supports_model_field(model_class: type, field_name: str) -> bool:
    fields = _model_fields(model_class)
    if field_name in fields:
        return True

    return any(getattr(field, "alias", None) == field_name for field in fields.values())


def _set_base_url_if_supported(
    model_class: type,
    model_kwargs: dict[str, object],
    base_url: str,
) -> None:
    for field_name in ("base_url", "api_base", "openai_api_base"):
        if _supports_model_field(model_class, field_name):
            model_kwargs[field_name] = base_url
            return


def _create_deepseek_model(
    model_config: ModelConfig,
    enable_thinking: bool,
):
    try:
        from langchain_deepseek import ChatDeepSeek
    except ImportError as exc:
        raise ModelConfigurationError(
            "Please install langchain-deepseek to use the DeepSeek LangChain model."
        ) from exc

    model_kwargs: dict[str, object] = {
        "model": model_config.model_name,
        "api_key": model_config.api_key,
    }
    _set_base_url_if_supported(ChatDeepSeek, model_kwargs, model_config.base_url)

    extra_body = _thinking_extra_body(model_config, enable_thinking)
    if extra_body is not None:
        if _supports_model_field(ChatDeepSeek, "extra_body"):
            model_kwargs["extra_body"] = extra_body
        else:
            model_kwargs["model_kwargs"] = extra_body

    return ChatDeepSeek(**model_kwargs)


def _create_qwen_model(
    model_config: ModelConfig,
    enable_thinking: bool,
):
    return ChatTongyi(
        model=model_config.model_name,
        api_key=model_config.api_key,
        streaming=True,
        model_kwargs={
            "enable_thinking": enable_thinking,
        },
    )


class webChatModelFactory(BaseModelFactory):
    def __init__(
        self,
        model_config: ModelConfig | None = None,
        enable_thinking: bool = True,
    ) -> None:
        self._model_config = model_config
        self._enable_thinking = enable_thinking

    def generator(self):
        model_config = self._model_config or get_model_config_service().get_active_model_config()
        if not model_config.api_key.strip():
            raise ModelConfigurationError("请先在管理员中心配置模型 API Key")

        if model_config.provider == "deepseek":
            return _create_deepseek_model(model_config, self._enable_thinking)

        if model_config.provider == "qwen":
            return _create_qwen_model(model_config, self._enable_thinking)

        model_kwargs = {
            "model_name": model_config.model_name,
            "base_url": model_config.base_url,
            "api_key": model_config.api_key,
        }
        extra_body = _thinking_extra_body(model_config, self._enable_thinking)
        if extra_body is not None:
            model_kwargs["extra_body"] = extra_body

        return ChatOpenAI(**model_kwargs)

class bendiChatModelFactory(BaseModelFactory):
    def generator(self):
        return ChatOllama(model="llama3.1")

PROJECT_ROOT = Path(__file__).parent.parent

class EmbeddingsFactory(BaseModelFactory):
    def generator(self) :
        return  HuggingFaceBgeEmbeddings(
            model_name=str(PROJECT_ROOT/rag_conf["embedding_model_name"]),  # 本地路径
            model_kwargs={"device": "cpu"},
            encode_kwargs={
                "normalize_embeddings": True,  # BGE 系列必须开启
                "batch_size": 32
            },
            # 🔑 关键：BGE 的 query instruction 前缀
            query_instruction="为这个句子生成表示以用于检索相关文章："
        )

def create_webchat_model(
    model_config: ModelConfig | None = None,
    enable_thinking: bool = True,
):
    return webChatModelFactory(model_config, enable_thinking).generator()


embedding_model=EmbeddingsFactory().generator()
