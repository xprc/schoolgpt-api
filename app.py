import time

import streamlit as st
from agent.react_agent import ReactAgent

st.title("百事通")
st.divider()

if "message" not in st.session_state:
    st.session_state["message"] = [{"role": "assistant", "content": "你好，我是百事通，请问有什么可以帮助你？"}]

if "agent" not in st.session_state:
    st.session_state["agent"] = ReactAgent()

for message in st.session_state["message"]:
    st.chat_message(message["role"]).write(message["content"])

# 在页面最下方提供用户输入栏
prompt = st.chat_input()

if prompt:
    # 在页面输出用户的提问
    st.chat_message("user").write(prompt)
    st.session_state["message"].append({"role": "user", "content": prompt})

    response_messages = []
    with st.spinner("智能客服思考中..."):
        res_stream = st.session_state["agent"].execute_stream(prompt)

        def capture(generator, cache_list):
            for chunk in generator:
                cache_list.append(chunk)

                for char in chunk:
                    time.sleep(0.01)
                    yield char

        st.chat_message("assistant").write_stream(capture(res_stream, response_messages))
        st.session_state["message"].append({"role": "assistant", "content": response_messages[-1]})
        st.rerun()
#
#
# import time
# import streamlit as st
# from agent.react_agent import ReactAgent
#
# # ==========================================
# # 🎨 1. 注入炫酷 UI 样式 (CSS)
# # ==========================================
# st.markdown("""
# <style>
# /* 隐藏默认页头页脚 */
# #MainMenu {visibility: hidden;}
# footer {visibility: hidden;}
# .stDeployButton {display:none;}
#
# /* 全局背景与字体 */
# .main .block-container {
#     background: linear-gradient(135deg, #0B0F19 0%, #1A1D2E 50%, #0D1117 100%);
#     min-height: 100vh;
#     border-radius: 20px;
#     padding: 2rem;
# }
# body {
#     font-family: 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
#     background: #0B0F19;
#     color: #E5E7EB;
# }
#
# /* 标题发光动画 */
# @keyframes neon-glow {
#     0% { text-shadow: 0 0 5px #3B82F6; }
#     50% { text-shadow: 0 0 20px #60A5FA, 0 0 40px #3B82F6; }
#     100% { text-shadow: 0 0 5px #3B82F6; }
# }
# .title-glow {
#     animation: neon-glow 2.5s infinite;
#     text-align: center;
#     font-weight: 700;
#     letter-spacing: 2px;
# }
#
# /* 滚动条美化 */
# ::-webkit-scrollbar { width: 6px; height: 6px; }
# ::-webkit-scrollbar-track { background: #1A1D2E; border-radius: 4px; }
# ::-webkit-scrollbar-thumb { background: #3B82F6; border-radius: 4px; }
# ::-webkit-scrollbar-thumb:hover { background: #2563EB; }
#
# /* 输入框与按钮美化 */
# .stChatInput > div > input {
#     background: rgba(255,255,255,0.05) !important;
#     border: 1px solid rgba(255,255,255,0.15) !important;
#     border-radius: 12px !important;
#     color: #F3F4F6 !important;
#     font-size: 15px !important;
# }
# .stChatInput > div > input:focus {
#     border-color: #3B82F6 !important;
#     box-shadow: 0 0 12px rgba(59,130,246,0.3) !important;
# }
# .stButton > button {
#     background: linear-gradient(90deg, #3B82F6, #8B5CF6) !important;
#     border: none !important;
#     color: white !important;
#     font-weight: 600 !important;
#     border-radius: 8px !important;
#     transition: all 0.3s ease !important;
# }
# .stButton > button:hover {
#     transform: translateY(-1px);
#     box-shadow: 0 4px 15px rgba(59,130,246,0.4) !important;
# }
#
# /* 消息气泡微调 */
# [data-testid="stChatMessage"] {
#     background: rgba(255,255,255,0.03) !important;
#     border: 1px solid rgba(255,255,255,0.08) !important;
#     border-radius: 14px !important;
#     padding: 12px 16px !important;
#     margin: 4px 0 !important;
# }
# </style>
# """, unsafe_allow_html=True)
#
# # ==========================================
# # 💬 2. 页面布局与状态管理
# # ==========================================
# st.markdown('<h1 class="title-glow">🌌 百事通 AI 助手</h1>', unsafe_allow_html=True)
# st.caption("🔹 基于 LangChain + RAG 智能问答 | 🔄 支持多轮对话与流式输出")
# st.divider()
#
# # 初始化会话状态
# if "messages" not in st.session_state:
#     st.session_state.messages = [
#         {"role": "assistant", "content": "你好！我是百事通，有什么可以帮你的？✨"}
#     ]
#
# if "agent" not in st.session_state:
#     with st.spinner("🔧 正在加载 AI 核心引擎..."):
#         st.session_state.agent = ReactAgent()
#
# # ==========================================
# # 📜 3. 渲染历史聊天记录
# # ==========================================
# for msg in st.session_state.messages:
#     with st.chat_message(msg["role"]):
#         st.markdown(msg["content"])
#
# # ==========================================
# # ⚙️ 4. 侧边栏控制面板
# # ==========================================
# with st.sidebar:
#     st.subheader("🎛️ 控制面板")
#     if st.button("🗑️ 清空对话记录", use_container_width=True):
#         st.session_state.messages = [
#             {"role": "assistant", "content": "对话已清空，请重新提问 🔄"}
#         ]
#         st.rerun()
#
#     st.markdown("---")
#     st.info("💡 **使用提示**\n- 支持自然语言多轮问答\n- 历史上下文自动记忆\n- 输出为逐字流式渲染")
#     st.success(f"🤖 Agent 状态: `{'✅ 已就绪' if st.session_state.agent else '⏳ 初始化中'}`")
#
# # ==========================================
# # 🚀 5. 用户输入与流式响应处理
# # ==========================================
# prompt = st.chat_input("输入你的问题，按 Enter 发送...")
#
# if prompt:
#     # ① 显示用户消息并保存历史
#     with st.chat_message("user"):
#         st.markdown(prompt)
#     st.session_state.messages.append({"role": "user", "content": prompt})
#
#     # ② 显示 AI 消息容器
#     with st.chat_message("assistant"):
#         response_placeholder = st.empty()
#         full_response = ""
#
#         # 使用流式生成器逐字输出
#         with st.spinner("🧠 正在深度思考中..."):
#             for chunk in st.session_state.agent.execute_stream(prompt):
#                 full_response += chunk
#                 response_placeholder.markdown(full_response)
#                 time.sleep(0.015)  # 控制打字速度（可调整 0.01~0.03）
#
#         # ③ 保存完整回复到历史记录
#         st.session_state.messages.append({"role": "assistant", "content": full_response})
#
#     # ④ 刷新页面以固定最新状态（避免流式结束后消失）
#     st.rerun()