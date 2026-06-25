"""
总结服务类：用户提问，搜索参考资料，将提问和参考资料提交给模型，让模型总结回复
"""
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

from api.services.model_config_service import get_model_config_service
from model.factory import create_webchat_model
from rag.vector_store import VectorStoreService
from utils.prompt_loader import load_rag_prompt


class RagSummarylize(object):
    def __init__(self):
        self.vector_store=VectorStoreService()
        self.retriever = self.vector_store.get_retriever()
        self.prompt_text=load_rag_prompt()
        self.prompt_template=PromptTemplate.from_template(self.prompt_text)
        self.chain=None
        self.model_cache_key=None



    def _get_chain(self):
        model_config = get_model_config_service().get_active_model_config()
        if self.chain is None or self.model_cache_key != model_config.cache_key:
            self.chain=self.prompt_template | create_webchat_model(model_config) | StrOutputParser()
            self.model_cache_key=model_config.cache_key

        return self.chain

    def retriever_docs(self,query):
        return self.retriever.invoke(query)

    def rag_summarize(self,query):
        context_docs=self.retriever_docs(query)
        context=""
        counter=0
        for doc in context_docs:
            counter+=1
            context+=f"【参考资料{counter}】: 参考资料: {doc.page_content} | 参考元数据: {doc.metadata}\n"

        return self._get_chain().invoke(
            {
                "input":query,
                "context":context,
            }
        )
