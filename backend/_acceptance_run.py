"""AI 能力页 22 个功能端到端验收脚本。

用法: python -X utf8 _acceptance_run.py <start_index> <count>
逐项通过 Agent 问答触发工具，记录: 工具调用序列 / 是否失败 / 答案摘要 / 耗时。
"""

import asyncio
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8081/api/v1"
TOKEN = None


def api(path, method="GET", body=None, timeout=60):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}),
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", errors="replace")
        return json.loads(raw) if raw else None


def ask_agent(resume_id: int, question: str, timeout: int = 240, conversation_id: int | None = None) -> dict:
    """调 /ask/agent，解析 SSE 事件流。返回 {tools, failed, answer, usage, seconds}。

    对齐前端链路（QAPage.askAgentStream）：
    - 携带 conversation_id（前端 activeConversationId）
    - 处理 approval_request 事件 → 自动 POST /qa/approval 批准（前端弹窗确认后同路径回传）
      （D1 审批门：web_search / search_jobs_live 等工具 requires_approval=True，
       不处理审批会挂起 120s 超时——这是脚本链路 ≠ 前端链路的典型差异）
    """
    import threading

    req = urllib.request.Request(
        BASE + "/qa/ask/agent",
        data=json.dumps(
            {
                "resume_id": resume_id,
                "question": question,
                **({"conversation_id": conversation_id} if conversation_id else {}),
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"},
    )
    tools: list[str] = []
    answer = ""
    error = None
    usage = {}
    approvals_seen = 0
    start = time.monotonic()

    def _approve(aid: str) -> None:
        """模拟前端审批弹窗点击「批准」（与 QAPage L1744 同路径：approval_id + decision=approved）。"""
        try:
            api(
                "/qa/approval",
                "POST",
                {"approval_id": aid, "decision": "approved"},
                timeout=15,
            )
        except Exception as e:
            print(f"  !! 审批回传失败 {aid}: {e}")

    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw_line in r:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                ev = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            t = ev.get("type")
            if t == "tool_call":
                tools.append(ev.get("tool_name") or ev.get("name") or "?")
            elif t == "approval_request":
                # 并行回传审批决议（SSE 主循环阻塞，需独立线程）
                aid = ev.get("approval_id") or ""
                if aid:
                    approvals_seen += 1
                    threading.Thread(target=_approve, args=(aid,), daemon=True).start()
            elif t == "agent_done":
                answer = ev.get("answer") or ""
                usage = ev.get("token_usage") or {}
            elif t == "error":
                error = ev.get("message") or "error"
    seconds = round(time.monotonic() - start, 1)
    return {
        "tools": tools,
        "failed": error,
        "answer": answer,
        "usage": usage,
        "seconds": seconds,
        "approvals": approvals_seen,
    }


# ── 22 个能力功能（对应 AI 能力页分组） ──
CASES = [
    # 诊断分析
    ("简历诊断", "请全面诊断这份简历的完整性和质量，给出改进建议"),
    ("模块检查", "帮我检查简历各模块的完整性和 ATS 兼容性"),
    ("信息追问", "根据简历现状，帮我梳理还需要补充哪些信息"),
    ("简历对比", "请对比简历 104 和简历 102 的优劣势，分析各自的亮点和不足"),
    # 岗位匹配
    ("JD 匹配", "请分析这份简历与以下岗位描述的匹配度，指出差距在哪里：\n\n岗位：大模型应用开发工程师，要求熟悉 FastAPI、LangChain/LangGraph、向量数据库、RAG 技术栈，有 Agent 开发经验"),
    ("岗位推荐", "请实时搜索最近的 AI 方向校招和社招岗位机会"),
    ("联网搜索", "搜索一下最近的 AI 岗位面试经验（面经）"),
    # 简历创作
    ("整份优化", "请按目标岗位【大模型应用开发工程师】优化这份简历，让它更专业更有竞争力"),
    ("模块生成", "帮我生成简历中缺失的模块内容，比如证书或荣誉奖项"),
    ("STAR 改写", "用 STAR 法则改写我简历里的经历描述，让它们更有说服力"),
    ("定向修改", "帮我定向修改简历中的技能模块，把技能按熟练度排序并分组成核心技术栈和工具类"),
    # 文档输出
    ("翻译", "帮我把这份简历翻译成英文"),
    ("求职信", "帮我在这个简历的基础上，针对【大模型应用开发工程师】岗位写一封求职信"),
    # 面试辅导
    ("模拟面试", "请根据我的简历，帮我做一次目标岗位【大模型应用开发工程师】的模拟面试"),
    ("谈薪简报", "帮我生成【大模型应用开发工程师】岗位的谈薪简报"),
    # 知识检索
    ("简历检索", "帮我检索这份简历里关于项目经历的内容"),
    ("资产检索", "帮我在我的知识资产库（简历 / JD / 面试记录）里检索【RAG】相关内容"),
    ("面经知识库", "检索面经库里的后端面试题"),
    ("整文读取", "把这份简历的完整内容读取出来给我看看"),
    ("深度问答", "基于我的简历，深度回答：我的核心技术能力有哪些？并给出依据"),
    # 记忆
    ("记住", "请记住我的求职偏好：优先考虑大模型相关岗位"),
    ("回忆", "回忆一下我们之前聊过的关于我求职方向的内容"),
]


async def run_one(name: str, question: str, resume_id: int, conversation_id: int | None = None) -> dict:
    print(f"\n═══ {name} ═══")
    result = await asyncio.to_thread(ask_agent, resume_id, question, conversation_id=conversation_id)
    tools = " → ".join(result["tools"]) if result["tools"] else "（无工具调用）"
    print(f"  工具: {tools}")
    print(f"  耗时: {result['seconds']}s  失败: {result['failed'] or '无'}  审批: {result.get('approvals', 0)}")
    ans = result["answer"].strip().replace("\n", " ")
    print(f"  答案: {ans[:180]}")
    return {"name": name, **result}


async def main():
    global TOKEN
    start_idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    count = int(sys.argv[2]) if len(sys.argv) > 2 else len(CASES)
    resume_id = int(sys.argv[3]) if len(sys.argv) > 3 else 104

    TOKEN = api("/auth/login", "POST", {"email": "Tianhuayuan@test.com", "password": "test1234"})["access_token"]
    print(f"登录 OK，测试简历: {resume_id}")

    # 对齐前端：先创建会话（前端 createConversation: POST /qa/conversations/{resume_id}）
    conv = api(f"/qa/conversations/{resume_id}", "POST", {"title": "能力验收会话"})
    conversation_id = conv.get("id")
    print(f"会话 OK: {conversation_id}")

    results = []
    for name, question in CASES[start_idx : start_idx + count]:
        try:
            r = await run_one(name, question, resume_id, conversation_id)
            results.append(r)
        except Exception as e:
            print(f"  !! {name} 异常: {type(e).__name__} {str(e)[:200]}")
            results.append({"name": name, "failed": f"异常 {str(e)[:100]}", "seconds": 0, "tools": []})

    print("\n\n══════ 汇总 ══════")
    for r in results:
        status = "❌" if r.get("failed") else "✅"
        extra = f" 审批×{r.get('approvals',0)}" if r.get("approvals") else ""
        print(f"{status} {r['name']:8s} {r.get('seconds',0):6.1f}s{extra}  工具:[{','.join(r.get('tools',[]))}]")


asyncio.run(main())
