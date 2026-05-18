# import hashlib
# import os
#
# from langchain_community.document_loaders import CSVLoader, PyPDFLoader, TextLoader
#
#
# def get_file_md5_hex(filepath):
#
#     if not os.path.exists(filepath):
#         print(f"错误：文件{filepath} 不存在")
#         return None
#
#     if not os.path.isfile(filepath):
#         print(f"错误：{filepath}不是有效文件")
#         return None
#
#     md5_obj=hashlib.md5()#初始化md5对象
#     chunk_size=4096
#     try:
#         with open(filepath,"rb") as f:
#             while chunk :=f.read(chunk_size):
#                 md5_obj.update(chunk)
#
#             md5_hex=md5_obj.hexdigest()
#
#             return md5_hex
#     except PermissionError:
#         print(f"错误：无权限读取文件{filepath}")
#         return None
#     except Exception as e:
#         print(f"计算MD5失败{str(e)}")
#         return None
#
# def listdir_with_allowed_type(path:str,allowed_types:tuple[str]):
#     files=[]
#     print("x2",allowed_types,type(allowed_types))
#     if not os.path.isdir(path):
#         print(f"错误{path}不是有效目录或不存在")
#         return tuple(files)
#
#     for f in os.listdir(path):
#         print("x1",f)
#         if f.endswith(allowed_types):
#             print("x2",f)
#             files.append(os.path.join(path,f))
#
#     return tuple(files)
#
# def csv_loader(filepath,source_colum,encoding="utf-8",csv_args=None):
#     loader=CSVLoader(
#         filepath,
#         source_column=source_colum,
#         encoding=encoding,
#         csv_args=csv_args,
#     )
#     return loader.load()
#
# def pdf_loader(filepath,passwd=None):
#     return PyPDFLoader(filepath,passwd).load()
#
# def txt_loader(filepath):
#     return TextLoader(filepath,encoding="utf_8",autodetect_encoding=True).load()
#
#
#
#
#

import hashlib
import logging
import re
from pathlib import Path
from typing import List, Optional, Sequence, Tuple, Union
import pdfplumber
from langchain_core.documents import Document
from langchain_community.document_loaders import CSVLoader, TextLoader

# 配置日志（仅输出 WARNING 及以上，保持控制台清爽）
logging.basicConfig(level=logging.WARNING, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger(__name__)


# ================= 1. 文件校验与 MD5 =================
def get_file_md5_hex(filepath: Union[str, Path]) -> Optional[str]:
    """计算文件 MD5，用于去重或缓存校验"""
    filepath = Path(filepath)
    if not filepath.exists() or not filepath.is_file():
        logger.warning(f"文件不存在或无效: {filepath}")
        return None
    try:
        with open(filepath, "rb") as f:
            md5_obj = hashlib.md5()
            for chunk in iter(lambda: f.read(4096), b""):
                md5_obj.update(chunk)
            return md5_obj.hexdigest()
    except Exception as e:
        logger.error(f"MD5 计算失败 {filepath}: {e}")
        return None


def listdir_with_allowed_type(path: Union[str, Path], allowed_types: Sequence[str]) -> Tuple[Path, ...]:
    """过滤目录下指定后缀的文件，返回 Path 元组"""
    path = Path(path)
    if not path.is_dir():
        logger.error(f"目录不存在或无效: {path}")
        return ()

    allowed_exts = tuple(ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in allowed_types)
    return tuple(f for f in path.iterdir() if f.is_file() and f.suffix.lower() in allowed_exts)


# ================= 2. 文档加载器 =================
def txt_loader(filepath: Union[str, Path], encoding: str = "utf-8") -> List[Document]:
    """TXT 加载器：优先 LangChain，失败则 fallback 原生读取"""
    try:
        loader = TextLoader(str(filepath), encoding=encoding, autodetect_encoding=True)
        return loader.load()
    except Exception as e:
        logger.warning(f"TextLoader 失败，启用备用读取: {filepath} | {e}")
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            return [Document(page_content=content, metadata={"source": str(filepath)})]
        except Exception as e2:
            logger.error(f"TXT 备用读取也失败: {filepath} | {e2}")
            return []


def csv_loader(filepath: Union[str, Path], source_column: str = "source", encoding: str = "utf-8", **kwargs) -> List[
    Document]:
    """CSV 加载器：支持自定义源列与参数透传"""
    try:
        loader = CSVLoader(str(filepath), source_column=source_column, encoding=encoding, **kwargs)
        return loader.load()
    except Exception as e:
        logger.error(f"CSV 加载失败: {filepath} | {e}")
        return []


# ================= 3. PDF 高精度加载器（核心升级） =================
def _clean_pdf_raw_text(raw_text: str) -> str:
    """清洗 PDF 原始文本：去页码/页眉、合并断行、保留语义连贯性"""
    lines = raw_text.split('\n')
    cleaned = []
    # 根据你的文件特征自定义过滤词
    skip_keywords = ["北方工业大学", "人工智能与计算机学院", "附件："]

    for line in lines:
        line = line.strip()
        if not line:
            continue
        # 剔除孤立页码（如 "1", "2", "3"）
        if re.match(r'^\d{1,3}$', line):
            continue
        # 剔除页眉页脚特征
        if any(kw in line for kw in skip_keywords):
            continue
        cleaned.append(line)

    # 智能合并断行（非句末标点结尾的行自动拼接下一行）
    merged = []
    temp = ""
    for line in cleaned:
        if temp and not re.search(r'[。！？；：\n.!?;:\n]', temp):
            temp += line
        else:
            if temp:
                merged.append(temp)
            temp = line
    if temp:
        merged.append(temp)
    return "\n".join(merged)


def _extract_tables_to_markdown(page) -> str:
    """提取 PDF 表格并转为 Markdown 格式，保留结构关系"""
    tables = page.extract_tables()
    if not tables:
        return ""
    md_blocks = []
    for tbl in tables:
        if not tbl or len(tbl) < 2:
            continue
        header = "| " + " | ".join(str(c or "") for c in tbl[0]) + " |"
        sep = "|---" * len(tbl[0]) + "|"
        rows = ["| " + " | ".join(str(c or "") for c in row) + " |" for row in tbl[1:]]
        md_blocks.append(f"\n{header}\n{sep}\n" + "\n".join(rows))
    return "\n".join(md_blocks)


def pdf_loader(filepath: Union[str, Path], password: Optional[str] = None) -> List[Document]:
    """高精度 PDF 加载器：pdfplumber + 智能清洗 + 表格转 Markdown"""
    filepath = Path(filepath)
    try:
        with pdfplumber.open(str(filepath), password=password) as pdf:
            full_content = []
            for i, page in enumerate(pdf.pages, 1):
                text = page.extract_text() or ""
                cleaned = _clean_pdf_raw_text(text)
                tables_md = _extract_tables_to_markdown(page)

                if cleaned:
                    full_content.append(f"## 第 {i} 页\n{cleaned}")
                if tables_md:
                    full_content.append(f"## 第 {i} 页表格\n{tables_md}")

            if not full_content:
                logger.warning(f"PDF 提取后无有效内容: {filepath}")
                return []

            return [Document(
                page_content="\n\n".join(full_content),
                metadata={"source": str(filepath), "file_type": "pdf"}
            )]
    except Exception as e:
        logger.error(f"PDF 加载失败: {filepath} | {e}")
        return []


# ================= 4. 统一路由入口（推荐在 vector_store.py 中调用） =================
def load_file(filepath: Union[str, Path]) -> List[Document]:
    """智能路由：根据后缀自动选择加载器"""
    filepath = Path(filepath)
    suffix = filepath.suffix.lower()

    if suffix == ".txt":
        return txt_loader(filepath)
    elif suffix == ".csv":
        return csv_loader(filepath)
    elif suffix == ".pdf":
        return pdf_loader(filepath)
    else:
        logger.warning(f"不支持的文件类型: {suffix}")
        return []