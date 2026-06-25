from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

from api.services.model_config_service import get_model_config_service
from model.factory import create_webchat_model
from rag.source_context import add_rag_sources
from rag.vector_store import get_vector_store_service
from utils.prompt_loader import load_policy_rag_search_prompt


class PolicyRagSearchService(object):
    def __init__(self):
        self.vector_store = get_vector_store_service()
        self.retriever = self.vector_store.get_retriever()
        self.prompt_text = load_policy_rag_search_prompt()
        self.prompt_template = PromptTemplate.from_template(self.prompt_text)
        self.chain = None
        self.model_cache_key = None

    def _get_chain(self):
        model_config = get_model_config_service().get_active_model_config()
        if self.chain is None or self.model_cache_key != model_config.cache_key:
            self.chain = self.prompt_template | create_webchat_model(model_config) | StrOutputParser()
            self.model_cache_key = model_config.cache_key

        return self.chain

    def retriever_docs(self, query):
        return self.vector_store.similarity_search_with_sources(query)

    def policy_rag_search(self, query):
        context_docs = self.retriever_docs(query)
        add_rag_sources([
            {
                "file_name": item["file_name"],
                "confidence": item["confidence"],
            }
            for item in context_docs
        ])

        context = ""
        for counter, item in enumerate(context_docs, 1):
            doc = item["document"]
            context += (
                f"[reference {counter}] "
                f"confidence: {item['confidence']:.4f} | "
                f"content: {doc.page_content} | "
                f"metadata: {doc.metadata}\n"
            )

        return self._get_chain().invoke(
            {
                "input": query,
                "context": context,
            }
        )
