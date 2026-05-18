from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import asyncio

# 从你的项目中引入 ReactAgent 类
from agent.react_agent import ReactAgent

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    query: str


# 1. 定义一个依赖函数，用于验证请求头中的 Token
async def verify_token(authorization: str = Header(None)):
    # 设定你的专属 Token
    expected_token = "Bearer hajimionanbeiluduo0xx"

    # 校验请求头是否包含正确的 Token
    if not authorization or authorization != expected_token:
        raise HTTPException(status_code=401, detail="未授权：Token 无效或缺失")


# 2. 将依赖注入到路由中 (dependencies 列表)
@app.post("/api/chat", dependencies=[Depends(verify_token)])
async def chat_stream_endpoint(request: ChatRequest):
    ang = ReactAgent()

    async def generate_stream():
        result = ang.execute_stream(request.query)
        for chunk in result:
            for char in chunk:
                await asyncio.sleep(0.01)
                yield f"data: {char}\n\n"

    return StreamingResponse(generate_stream(), media_type="text/event-stream")


if __name__ == '__main__':
    uvicorn.run(app, host="0.0.0.0", port=8000)