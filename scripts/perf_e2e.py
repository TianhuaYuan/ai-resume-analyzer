#!/usr/bin/env python3
"""T38: 端到端性能测试脚本（真实模型，无 mock）。

对一个真实运行的后端（FastAPI + LLM 服务）跑完整链路并测量关键性能指标：

  1. 认证：--email/--password 直接登录；未提供则自动注册全新用户（send-code → register → login）
  2. 简历准备：--resume-file 上传真实简历文件；未提供则通过 POST /resumes/builder
     创建 builder 简历并 mode=complete 保存（真实向量化），轮询至 status=ready
  3. 每个问题：POST /api/v1/qa/ask/agent 走 SSE 流式，测量
     - 首 token 延迟（从请求发出到首个 SSE 事件）
     - 首 tool_call 延迟（从请求发出到首个 tool_call 事件）
     - 总耗时
     - 工具调用次数（process_trace 中 type=tool_call 的数量）+ 最终答案长度
  4. 结果导出 JSON：auth_ms / resume_prep_ms / questions[] / summary{p50,p95,p99}

关键设计：
- 全程真实 API 调用，不 mock 任何服务；SSE 手动解析（无 sseclient 依赖）
- 任何一步失败只记录 error 字段并继续，绝不崩溃
- 自动注册的验证码为服务端随机生成（backend/services/verification_service.py），
  脚本无法通过 API 读取。默认尝试固定验证码 --verification-code（默认 123456）：
    - 后端若配置了固定码/测试模式 → 直接成功
    - 否则 register 返回 400 → 记录 error 并给出提示，可改用 --email/--password
      或先用 EMAIL_PROVIDER=log 模式下从后端日志读出验证码再传 --verification-code

依赖：httpx（backend/requirements.txt 已含）
用法:
    python scripts/perf_e2e.py --base-url http://localhost:8000 \
        --email user@test.com --password Test1234! --resume-file resume.pdf
"""

import argparse
import asyncio
import json
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

# ── 常量 ──────────────────────────────────────────────────────
STREAM_TIMEOUT = 180.0        # SSE 流超时（Agent 多轮工具调用需较长超时）
REQUEST_TIMEOUT = 30.0        # 非 SSE 请求超时
POLL_TIMEOUT = 120.0          # 简历处理轮询总超时
POLL_INTERVAL = 1.5           # 轮询间隔（与前端一致）
DEFAULT_QUESTIONS = "我的简历匹配这个 JD 吗,帮我优化简历中的项目描述"
DEFAULT_VERIFICATION_CODE = "123456"
AUTO_REGISTER_PASSWORD = "PerfTest123!"

# 若 --email/--password 均已提供则跳过注册直接登录

# ── ANSI 颜色码（终端美化，非必选） ────────────────────────────
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_CYAN = "\033[36m"


def _fmt_ms(ms: float | None) -> str:
    """格式化毫秒为可读字符串。"""
    if ms is None:
        return f"{_DIM}N/A{_RESET}"
    return f"{ms:>9.0f}ms"


def _fmt_label(label: str, width: int = 16) -> str:
    return f"{label:<{width}}"


def _print_header(title: str) -> None:
    print(f"\n{_BOLD}{_CYAN}{'=' * 64}{_RESET}")
    print(f"{_BOLD}{_CYAN}  {title}{_RESET}")
    print(f"{_BOLD}{_CYAN}{'=' * 64}{_RESET}")


def _print_step(num: int, title: str) -> None:
    print(f"\n{_BOLD}[{num}] {title}{_RESET}")


# ── 数据结构 ──────────────────────────────────────────────────


@dataclass
class QuestionResult:
    """单次 Agent SSE 流式请求的测量结果。"""

    question: str
    first_token_ms: float | None = None    # 请求发出 → 首个 SSE 事件
    first_tool_call_ms: float | None = None  # 请求发出 → 首个 tool_call 事件
    total_ms: float | None = None          # 请求发出 → 流结束
    tool_count: int = 0                    # process_trace 中 tool_call 数量
    answer_len: int = 0                    # 最终答案字符数
    error: str | None = None               # 失败原因（成功为 None）


def _percentile(sorted_values: list[float], p: float) -> float:
    """nearest-rank 百分位。sorted_values 升序。"""
    if not sorted_values:
        return 0.0
    idx = max(0, min(len(sorted_values) - 1, int(round(p / 100 * len(sorted_values))) - 1))
    return sorted_values[idx]


# ── 认证 ──────────────────────────────────────────────────────


async def login(client: httpx.AsyncClient, base_url: str, email: str, password: str) -> str:
    """登录获取 access_token。失败抛 HTTPError/ConnectError。"""
    resp = await client.post(
        f"{base_url}/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"登录响应缺少 access_token: {data}")
    return token


async def register_and_login(
    client: httpx.AsyncClient,
    base_url: str,
    verification_code: str,
) -> tuple[str, str]:
    """自动注册全新用户并登录。

    流程：send-code → register（固定验证码）→ login。
    验证码由服务端随机生成（verification_service），脚本无法读取；
    若 register 返回 400，抛出带说明的 RuntimeError。

    Returns:
        (access_token, email)
    """
    email = f"perf_{int(time.time())}_{uuid.uuid4().hex[:6]}@test.local"

    resp = await client.post(
        f"{base_url}/api/v1/auth/send-code",
        json={"email": email},
    )
    resp.raise_for_status()

    resp = await client.post(
        f"{base_url}/api/v1/auth/register",
        json={
            "email": email,
            "username": f"perf{uuid.uuid4().hex[:6]}",
            "password": AUTO_REGISTER_PASSWORD,
            "password_confirm": AUTO_REGISTER_PASSWORD,
            "verification_code": verification_code,
        },
    )
    if resp.status_code == 400:
        raise RuntimeError(
            "自动注册失败：验证码被拒（400）。验证码由后端随机生成且无法通过 API 读取。"
            "请改用 --email/--password 登录已有账号，"
            "或在 EMAIL_PROVIDER=log 环境下从后端日志读取验证码后传 --verification-code。"
            f"（详情: {resp.text[:200]}）"
        )
    resp.raise_for_status()

    token = await login(client, base_url, email, AUTO_REGISTER_PASSWORD)
    return token, email


async def auth_flow(args: argparse.Namespace) -> tuple[str | None, float, str | None]:
    """认证流程：登录或注册+登录。测量耗时。

    Returns:
        (access_token | None, auth_ms, error | None)
    """
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            if args.email and args.password:
                token = await login(client, args.base_url, args.email, args.password)
                mode = f"login({args.email})"
            else:
                token, email = await register_and_login(
                    client, args.base_url, args.verification_code
                )
                mode = f"register+login({email})"
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"  {_fmt_label('方式')} {mode}")
        print(f"  {_fmt_label('耗时')} {elapsed:.0f}ms")
        print(f"  {_fmt_label('Token')} {_DIM}{token[:16]}...{_RESET}")
        return token, elapsed, None
    except httpx.HTTPStatusError as e:
        msg = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
    except httpx.ConnectError as e:
        msg = f"无法连接 {args.base_url}（{e}），请确认服务已启动"
    except httpx.TimeoutException:
        msg = "认证请求超时"
    except RuntimeError as e:
        msg = str(e)
    except Exception as e:  # noqa: BLE001 — 记录任何异常继续
        msg = f"{type(e).__name__}: {e}"

    elapsed = (time.perf_counter() - t0) * 1000
    print(f"  {_RED}认证失败: {msg}{_RESET}")
    return None, elapsed, msg


# ── 简历准备 ──────────────────────────────────────────────────


def _builder_payload() -> dict:
    """构造一个最小可用的 builder 简历（4 个核心模块）。"""
    return {
        "filename": "perf-builder-resume",
        "modules": [
            {
                "module_type": "basic_info",
                "content": {
                    "name": "性能测试候选人",
                    "job_title": "后端工程师",
                    "summary": "3 年 Python 后端开发经验，熟悉 FastAPI 与 RAG 检索系统。",
                },
                "sort_order": 0,
            },
            {
                "module_type": "education",
                "content": {
                    "entries": [
                        {
                            "school": "示例大学",
                            "degree": "本科",
                            "major": "计算机科学与技术",
                            "start_date": "2018-09",
                            "end_date": "2022-06",
                        }
                    ]
                },
                "sort_order": 1,
            },
            {
                "module_type": "work_experience",
                "content": {
                    "entries": [
                        {
                            "company": "示例科技",
                            "position": "Python 后端开发",
                            "start_date": "2022-07",
                            "description": (
                                "负责简历解析与 RAG 检索系统开发，使用 FastAPI、ChromaDB "
                                "与 LangGraph 搭建 Agentic RAG 问答链路。"
                            ),
                            "achievements": ["将问答首反馈延迟优化到 3 秒内"],
                        }
                    ]
                },
                "sort_order": 2,
            },
            {
                "module_type": "skills",
                "content": {
                    "categories": [
                        {"name": "编程语言", "items": ["Python", "TypeScript"]},
                        {"name": "框架", "items": ["FastAPI", "React", "LangGraph"]},
                    ]
                },
                "sort_order": 3,
            },
        ],
        "style": {"template_id": "default"},
    }


def _mime_for(path: str) -> str:
    """按扩展名推断 MIME（上传用）。"""
    ext = Path(path).suffix.lower()
    return {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".txt": "text/plain",
        ".md": "text/markdown",
    }.get(ext, "application/octet-stream")


async def _wait_ready(
    client: httpx.AsyncClient, base_url: str, token: str, resume_id: int
) -> tuple[str, float, str | None]:
    """轮询 GET /resumes/{id} 直到 status=ready（超时 POLL_TIMEOUT）。

    Returns:
        (status, elapsed_ms, error | None)
    """
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < POLL_TIMEOUT:
        resp = await client.get(
            f"{base_url}/api/v1/resumes/{resume_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        status = resp.json().get("status")
        if status == "ready":
            return "ready", (time.perf_counter() - t0) * 1000, None
        if status == "failed":
            msg = resp.json().get("status_message") or "简历处理失败"
            return "failed", (time.perf_counter() - t0) * 1000, msg
        await asyncio.sleep(POLL_INTERVAL)
    return "timeout", POLL_TIMEOUT * 1000, f"轮询超时（{POLL_TIMEOUT:.0f}s），简历未就绪"


async def upload_resume_file(
    client: httpx.AsyncClient, base_url: str, token: str, resume_file: str
) -> tuple[int, str, float, str | None]:
    """上传简历文件（multipart）并轮询至 ready。

    Returns:
        (resume_id, mode, elapsed_ms, error | None)
    """
    t0 = time.perf_counter()
    file_path = Path(resume_file)
    if not file_path.is_file():
        return 0, "upload", 0, f"简历文件不存在: {resume_file}"

    try:
        with file_path.open("rb") as f:
            resp = await client.post(
                f"{base_url}/api/v1/resumes",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Idempotency-Key": f"perf-{uuid.uuid4().hex[:12]}",
                },
                files={"file": (file_path.name, f, _mime_for(str(file_path)))},
            )
            resp.raise_for_status()
            data = resp.json()
            resume_id = data.get("id")
            if not resume_id:
                return 0, "upload", 0, f"上传响应缺少 id: {data}"
    except httpx.HTTPStatusError as e:
        return 0, "upload", (time.perf_counter() - t0) * 1000, (
            f"上传失败 HTTP {e.response.status_code}: {e.response.text[:200]}"
        )
    except httpx.TimeoutException:
        return 0, "upload", (time.perf_counter() - t0) * 1000, "上传请求超时"

    status, wait_ms, err = await _wait_ready(client, base_url, token, resume_id)
    return resume_id, "upload", (time.perf_counter() - t0) * 1000, err or (
        None if status == "ready" else f"简历状态: {status}"
    )


async def create_builder_resume(
    client: httpx.AsyncClient, base_url: str, token: str
) -> tuple[int, str, float, str | None]:
    """创建 builder 简历：POST /resumes/builder → PUT ?mode=complete → ready。

    Returns:
        (resume_id, mode, elapsed_ms, error | None)
    """
    t0 = time.perf_counter()
    headers = {"Authorization": f"Bearer {token}"}
    payload = _builder_payload()

    try:
        resp = await client.post(
            f"{base_url}/api/v1/resumes/builder", json=payload, headers=headers
        )
        resp.raise_for_status()
        data = resp.json()
        resume_id = data.get("id")
        version = data.get("version")
        if not resume_id or version is None:
            return 0, "builder", (time.perf_counter() - t0) * 1000, f"builder 响应缺字段: {data}"

        # 保存并完成（乐观锁 version 必须匹配）
        resp = await client.put(
            f"{base_url}/api/v1/resumes/{resume_id}?mode=complete",
            json={"version": version, "modules": payload["modules"], "style": payload["style"]},
            headers=headers,
        )
        if resp.status_code == 409:
            return resume_id, "builder", (time.perf_counter() - t0) * 1000, (
                "保存并完成返回 409（版本冲突/状态不允许）: " + resp.text[:200]
            )
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        return 0, "builder", (time.perf_counter() - t0) * 1000, (
            f"builder 创建失败 HTTP {e.response.status_code}: {e.response.text[:200]}"
        )
    except httpx.TimeoutException:
        return 0, "builder", (time.perf_counter() - t0) * 1000, "builder 创建请求超时"

    status, wait_ms, err = await _wait_ready(client, base_url, token, resume_id)
    return resume_id, "builder", (time.perf_counter() - t0) * 1000, err or (
        None if status == "ready" else f"简历状态: {status}"
    )


async def resume_prep_flow(
    args: argparse.Namespace, token: str
) -> tuple[int, str, float, str | None]:
    """简历准备：上传文件或创建 builder 简历，轮询至 ready。

    Returns:
        (resume_id, mode, elapsed_ms, error | None)
    """
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        if args.resume_file:
            print(f"  {_fmt_label('方式')} upload({Path(args.resume_file).name})")
            return await upload_resume_file(client, args.base_url, token, args.resume_file)
        print(f"  {_fmt_label('方式')} builder（POST /resumes/builder + mode=complete）")
        return await create_builder_resume(client, args.base_url, token)


# ── SSE Agent 问答测量 ────────────────────────────────────────


def _parse_sse_events(text: str, buffer: str) -> tuple[list[dict], str]:
    """把原始 SSE 文本切块解析为事件列表。返回 (events, 剩余 buffer)。

    事件以空行分隔，每行形如 "data: {...}"。未闭合的尾部留在 buffer 等下一块。
    """
    text = text.replace("\r\n", "\n")
    buffer += text
    events: list[dict] = []
    while "\n\n" in buffer:
        block, buffer = buffer.split("\n\n", 1)
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                payload = line[5:].strip()
                if not payload:
                    continue
                try:
                    events.append(json.loads(payload))
                except json.JSONDecodeError:
                    pass
    return events, buffer


async def measure_agent_question(
    base_url: str, token: str, resume_id: int, question: str
) -> QuestionResult:
    """对单个问题跑 POST /api/v1/qa/ask/agent 并测量全部指标。"""
    result = QuestionResult(question=question)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    start = time.perf_counter()
    tool_call_events = 0

    try:
        async with httpx.AsyncClient(timeout=STREAM_TIMEOUT) as client:
            async with client.stream(
                "POST",
                f"{base_url}/api/v1/qa/ask/agent",
                headers=headers,
                json={"resume_id": resume_id, "question": question},
            ) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", errors="replace")
                    result.error = f"HTTP {resp.status_code}: {body[:200]}"
                    result.total_ms = (time.perf_counter() - start) * 1000
                    return result

                buffer = ""
                async for chunk in resp.aiter_text():
                    events, buffer = _parse_sse_events(chunk, buffer)
                    for event in events:
                        event_type = event.get("type")
                        elapsed_ms = (time.perf_counter() - start) * 1000
                        if result.first_token_ms is None:
                            result.first_token_ms = elapsed_ms  # 首个 SSE 事件
                        if event_type == "tool_call" and result.first_tool_call_ms is None:
                            result.first_tool_call_ms = elapsed_ms
                            tool_call_events += 1
                        elif event_type == "tool_call":
                            tool_call_events += 1
                        elif event_type == "agent_done":
                            result.answer_len = len(event.get("answer", ""))
                            trace = event.get("process_trace") or []
                            # 优先用 process_trace 统计工具数，兜底用 SSE 事件计数
                            tc = sum(1 for t in trace if t.get("type") == "tool_call")
                            result.tool_count = tc if tc else tool_call_events
                        elif event_type == "quota_exceeded":
                            result.error = f"配额不足: {event.get('message', '')}"
                        elif event_type == "error":
                            result.error = event.get("message", "Agent 内部错误")

                # 若 agent_done 未出现（流提前结束）
                if result.first_token_ms is not None and result.error is None and not buffer:
                    if result.answer_len == 0:
                        result.error = result.error or "流结束但未收到 agent_done 事件"
    except httpx.HTTPStatusError as e:
        result.error = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
    except httpx.ConnectError as e:
        result.error = f"连接失败: {e}"
    except httpx.ReadTimeout:
        result.error = f"流式请求超时（{STREAM_TIMEOUT:.0f}s）"
    except Exception as e:  # noqa: BLE001
        result.error = f"{type(e).__name__}: {e}"

    result.total_ms = (time.perf_counter() - start) * 1000
    return result


# ── 主流程 ────────────────────────────────────────────────────


def _print_question_row(idx: int, r: QuestionResult) -> None:
    """打印单题结果行。"""
    status = _GREEN + "OK" + _RESET if r.error is None else _RED + "FAIL" + _RESET
    print(
        f"  #{idx:<2} {r.question[:24]:<26} "
        f"首token {_fmt_ms(r.first_token_ms)}  "
        f"首tool {_fmt_ms(r.first_tool_call_ms)}  "
        f"总耗时 {_fmt_ms(r.total_ms)}  "
        f"工具 {r.tool_count:<2} 答案 {r.answer_len:<5} {status}"
    )
    if r.error:
        print(f"      {_DIM}→ {r.error}{_RESET}")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="T38: 端到端性能测试 — 真实模型 Agent SSE 全链路测量",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  # 用已有账号 + 上传简历\n"
            "  python scripts/perf_e2e.py --email user@test.com --password Test1234! \\\n"
            "      --resume-file resume.pdf\n"
            "  # 自动注册 + builder 简历（本地默认验证码 123456，可能被后端拒绝）\n"
            "  python scripts/perf_e2e.py\n"
            "  # 自定义问题与输出文件\n"
            "  python scripts/perf_e2e.py --email user@test.com --password Test1234! \\\n"
            "      --questions \"我的简历匹配这个 JD 吗,帮我优化简历中的项目描述\" \\\n"
            "      --output perf_results.json\n"
        ),
    )
    parser.add_argument("--base-url", default="http://localhost:8000", help="API 基础 URL")
    parser.add_argument("--email", default=None, help="登录邮箱（缺省则自动注册）")
    parser.add_argument("--password", default=None, help="登录密码（缺省则自动注册）")
    parser.add_argument(
        "--verification-code",
        default=DEFAULT_VERIFICATION_CODE,
        help="自动注册使用的验证码（默认 123456）",
    )
    parser.add_argument("--resume-file", default=None, help="简历文件路径（缺省则走 builder 流程）")
    parser.add_argument(
        "--questions",
        default=DEFAULT_QUESTIONS,
        help="逗号分隔的问题列表",
    )
    parser.add_argument("--output", default="perf_results.json", help="结果 JSON 输出路径")
    args = parser.parse_args()

    questions = [q.strip() for q in args.questions.split(",") if q.strip()]
    if not questions:
        print(f"{_RED}--questions 为空，至少需要一个问题{_RESET}")
        sys.exit(2)

    print(f"{_BOLD}端到端性能测试{_RESET} — {args.base_url}")
    print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"问题数: {len(questions)} | 简历来源: {args.resume_file or 'builder'}")
    print("─" * 64)

    results: dict[str, Any] = {
        "meta": {
            "base_url": args.base_url,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "questions": questions,
            "resume_source": "upload" if args.resume_file else "builder",
        },
        "auth_ms": None,
        "resume_prep_ms": None,
        "questions": [],
        "summary": None,
        "errors": [],
    }

    # ── 1. 认证 ──
    _print_step(1, "认证（登录 或 注册+登录）")
    token, auth_ms, auth_err = await auth_flow(args)
    results["auth_ms"] = auth_ms
    if auth_err:
        results["errors"].append(f"auth: {auth_err}")
        print(f"\n{_RED}认证失败，无法继续。{_RESET}")
        _dump_results(args.output, results)
        sys.exit(1)

    # ── 2. 简历准备 ──
    _print_step(2, "简历准备（上传 或 builder 新建，轮询至 ready）")
    resume_id, mode, prep_ms, prep_err = await resume_prep_flow(args, token)
    results["resume_prep_ms"] = prep_ms
    results["meta"]["resume_mode"] = mode
    print(f"  {_fmt_label('简历 ID')} {resume_id}")
    print(f"  {_fmt_label('耗时')} {prep_ms:.0f}ms")
    if prep_err:
        results["errors"].append(f"resume_prep: {prep_err}")
        print(f"  {_RED}简历准备失败: {prep_err}{_RESET}")
        print(f"\n{_RED}简历未就绪，跳过问答测试。{_RESET}")
        _dump_results(args.output, results)
        sys.exit(1)

    # ── 3. 逐个问题跑 Agent SSE ──
    _print_step(3, "Agent SSE 问答（POST /api/v1/qa/ask/agent）")
    q_results: list[QuestionResult] = []
    for idx, question in enumerate(questions, 1):
        print(f"\n  {_BOLD}[Q{idx}] {question}{_RESET}")
        r = await measure_agent_question(args.base_url, token, resume_id, question)
        _print_question_row(idx, r)
        q_results.append(r)
        if r.error:
            results["errors"].append(f"question[{idx}]: {r.error}")

    results["questions"] = [
        {
            "question": r.question,
            "first_token_ms": round(r.first_token_ms, 1) if r.first_token_ms is not None else None,
            "first_tool_call_ms": (
                round(r.first_tool_call_ms, 1) if r.first_tool_call_ms is not None else None
            ),
            "total_ms": round(r.total_ms, 1) if r.total_ms is not None else None,
            "tool_count": r.tool_count,
            "answer_len": r.answer_len,
            "error": r.error,
        }
        for r in q_results
    ]

    # ── 4. 汇总百分位（仅统计成功请求的 total_ms） ──
    ok_totals = sorted(
        r.total_ms for r in q_results if r.error is None and r.total_ms is not None
    )
    if ok_totals:
        results["summary"] = {
            "p50": round(_percentile(ok_totals, 50), 1),
            "p95": round(_percentile(ok_totals, 95), 1),
            "p99": round(_percentile(ok_totals, 99), 1),
        }
    else:
        results["summary"] = None

    # ── 汇总表 ──
    _print_header("性能汇总")
    print(f"  认证耗时    : {auth_ms:.0f}ms")
    print(f"  简历准备耗时: {prep_ms:.0f}ms")
    print()
    print(f"  {'#':<3} {'问题':<26} {'首token':<13} {'首tool_call':<14} {'总耗时':<13} {'工具':<5} {'答案':<7} 状态")
    print(f"  {'─' * 100}")
    for idx, r in enumerate(q_results, 1):
        _print_question_row(idx, r)
    print()
    if results["summary"]:
        s = results["summary"]
        print(
            f"  总耗时百分位: p50={s['p50']:.0f}ms | p95={s['p95']:.0f}ms | "
            f"p99={s['p99']:.0f}ms（{len(ok_totals)}/{len(q_results)} 成功）"
        )
    else:
        print(f"  {_RED}无成功请求，无法计算百分位{_RESET}")

    _dump_results(args.output, results)

    # 有失败 → 非零退出码（供 CI 判断）
    if results["errors"]:
        print(f"\n{_YELLOW}存在 {len(results['errors'])} 个错误，详见结果文件。{_RESET}")
        sys.exit(1)
    print(f"\n{_DIM}测试完成，结果已写入 {args.output}{_RESET}")


def _dump_results(output: str, results: dict[str, Any]) -> None:
    """将结果写入 JSON 文件（UTF-8）。"""
    try:
        with open(output, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"  {_DIM}结果已写入 {output}{_RESET}")
    except OSError as e:
        print(f"  {_RED}写入结果文件失败: {e}{_RESET}")


if __name__ == "__main__":
    asyncio.run(main())
