from abc import ABC,abstractmethod
from pathlib import Path

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


class webChatModelFactory(BaseModelFactory):
    def __init__(self, model_config: ModelConfig | None = None) -> None:
        self._model_config = model_config

    def generator(self):
        model_config = self._model_config or get_model_config_service().get_active_model_config()
        if not model_config.api_key.strip():
            raise ModelConfigurationError("请先在管理员中心配置模型 API Key")

        return ChatOpenAI(
            model_name=model_config.model_name,
            base_url=model_config.base_url,
            api_key=model_config.api_key,
        )

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

def create_webchat_model(model_config: ModelConfig | None = None):
    return webChatModelFactory(model_config).generator()


embedding_model=EmbeddingsFactory().generator()
