from abc import ABC,abstractmethod
from pathlib import Path
from typing import Optional
import dotenv
import os

from langchain_community.embeddings import HuggingFaceBgeEmbeddings

from utils.config_handler import rag_conf
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from sentence_transformers import SentenceTransformer
dotenv.load_dotenv()

class BaseModelFactory(ABC):

    @abstractmethod
    def generator(self):
        pass


class webChatModelFactory(BaseModelFactory):
    def generator(self):
        return ChatOpenAI(model_name=os.getenv("deepseek_modelname"),base_url=os.getenv("deepseek_baseurl"), api_key=os.getenv("deepseek_api_key"))

class bendiChatModelFactory(BaseModelFactory):
    def generator(self):
        return ChatOllama(model=os.getenv("Ollama_modelname"))

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

webchat_model = webChatModelFactory().generator()
bendichat_model = bendiChatModelFactory().generator()
embedding_model=EmbeddingsFactory().generator()
