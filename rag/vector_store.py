import os.path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
import tiktoken
from utils.config_handler import chroma_conf
from model.factory import embedding_model
from utils.file_handler import txt_loader, pdf_loader, csv_loader, listdir_with_allowed_type, get_file_md5_hex
from utils.path_tools import get_abs_path
from utils.logger_handler import logger

_token_encoder = tiktoken.get_encoding("cl100k_base")

def count_tokens(text: str) -> int:
    return len(_token_encoder.encode(text))

class VectorStoreService:
    def __init__(self):
        self.vector_store=Chroma(
            collection_name=chroma_conf["collection_name"],
            embedding_function=embedding_model,
            persist_directory=chroma_conf["persist_directory"],
        )
        self.spliter=RecursiveCharacterTextSplitter(
            chunk_size=chroma_conf["chunk_size"],
            chunk_overlap=chroma_conf["chunk_overlap"],
            separators=[
                "\n\n",  # 段落分隔
                "\n",     # 换行
                "。", "！", "？",  # 中文句末标点
                ".", "!", "?",  # 英文句末标点
                "；", ";",  # 分号
                "、", ",",  # 逗号
                " ", "",  # 空格和空字符串
            ],
            is_separator_regex=False,
            length_function=count_tokens,  # 🔑 关键：替换默认 len()
        )
    def get_retriever(self):
        return self.vector_store.as_retriever(search_type="similarity_score_threshold",
            search_kwargs={
                    "k": chroma_conf["k"],                    # 返回 Top-5
                    "score_threshold": chroma_conf["score_threshold"],   # 余弦相似度低于此值的片段直接过滤
                    "filter": chroma_conf["filter"]             # 可按 metadata 过滤，如 {"source": "doc1.pdf"}
            })

    def load_document(self):
        def check_md5_hex(md5_for_check:str):
            if not os.path.exists(get_abs_path(chroma_conf["md5_hex_store"])):
                #没有的话就创建一个文件重新整
                open(get_abs_path(chroma_conf["md5_hex_store"]),"w",encoding="utf_8").close()
                return False

            with open(get_abs_path(chroma_conf["md5_hex_store"]),"r",encoding="utf_8") as f:
                for line in f.readlines():
                    line=line.strip()
                    if line==md5_for_check:
                        return True


            return False

        def save_md5_hex(md5_for_save):
            with open(get_abs_path(chroma_conf["md5_hex_store"]),"a",encoding="utf-8") as f:
                f.write(md5_for_save+"\n")

        def get_file_documents(read_path:str):
            suffix = read_path.suffix.lower()
            if suffix == ".txt":
                return txt_loader(read_path)
            elif suffix == ".pdf":
                return pdf_loader(read_path)
            elif suffix == ".csv":
                return csv_loader(read_path, source_column="source")
            else:
                logger.warning(f"跳过不支持的文件类型: {suffix}")
                return []


        allowed_files_path=listdir_with_allowed_type(
            get_abs_path(chroma_conf["data_path"]),
            tuple(chroma_conf["allow_knowledge_file_type"])
        )

        for path in allowed_files_path:
            md5_hex=get_file_md5_hex(path)

            if not md5_hex:
                logger.warning(f"[加载知识库] {path} MD5计算失败，跳过")
                continue

            if check_md5_hex(md5_hex):
                logger.info(f"[加载知识库] {path} 内容已经存在于知识库，跳过")
                continue

            try:
                documents:list[Document]=get_file_documents(path)

                if not documents:
                    logger.warning(f"[加载知识库] {path}无有效内容，跳过")
                    continue

                split_document:list[Document]=self.spliter.split_documents(documents)

                if not split_document:
                    logger.warning(f"[加载知识库] {path}分片后无有效内容，跳过")
                    continue

                self.vector_store.add_documents(split_document)

                save_md5_hex(md5_hex)

                logger.info(f"[加载知识库] {path}内容加载成功")

            except Exception as e:
                # exc_info为True会记录详细报错堆栈，False仅记录报错str
                logger.error(f"[加载知识库] {path} 加载失败：{str(e)}", exc_info=True)
                continue
