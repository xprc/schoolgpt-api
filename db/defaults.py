DEFAULT_MODEL_PROVIDER = "deepseek"
MODEL_PROVIDER_DEFAULTS: dict[str, dict[str, object]] = {
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "api_path": "/chat/completions",
        "models": ("deepseek-v4-pro", "deepseek-v4-flash"),
    },
    "qwen": {
        "label": "通义千问",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_path": "/chat/completions",
        "models": ("qwen-plus", "qwen-max", "qwen-turbo"),
    },
}

WEB_SEARCH_PROVIDER = "tavily"
WEB_SEARCH_PROVIDER_LABEL = "Tavily"

PADDLE_OCR_PROVIDER = "baidu_aistudio"
PADDLE_OCR_PROVIDER_LABEL = "百度 AI Studio PaddleOCR"
PADDLE_OCR_MODEL = "PaddleOCR-VL-1.5"
