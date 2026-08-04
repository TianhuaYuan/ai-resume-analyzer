"""A3 Agent 评估框架测试入口（CI 自动收集：testpaths=tests，无需改 CI）。

覆盖：
1. 全部黄金任务通过（脚本化假模型 + 契约校验模拟，无真实 LLM）
2. 确定性验证：同任务重复运行 → 状态哈希一致（tau-bench 可复现性）
3. pass_at_k 纯函数（超几何公式 C(c,k)/C(n,k) 已知值）
4. summarize 报告格式与任务池 pass@k 统计
5. 状态哈希区分度：不同轨迹 → 不同哈希
"""

import pytest

from tests.agent_eval.golden_tasks import ALL_TASKS, ToolCallSpec
from tests.agent_eval.harness import (
    compute_state_hash,
    pass_at_k,
    run_evals,
    run_task,
    summarize,
)


# ═══════════════════════════════════════════════════════════════
# 黄金任务执行
# ═══════════════════════════════════════════════════════════════


class TestGoldenTasks:
    @pytest.mark.asyncio
    async def test_all_golden_tasks_pass(self):
        """评估套件全过：9 个黄金任务（含坏调用恢复/收敛鲁棒性任务）。"""
        for task in ALL_TASKS:
            result = await run_task(task)
            assert result.passed, f"{task.name} 失败: {result.failure}"

    @pytest.mark.asyncio
    async def test_success_trajectory_recorded(self):
        """多工具链任务记录两条成功动作。"""
        from tests.agent_eval.golden_tasks import MULTI_TOOL_CHAIN_TASK

        result = await run_task(MULTI_TOOL_CHAIN_TASK)
        assert [a.name for a in result.actual_actions] == ["search_resume", "answer_from_index"]

    @pytest.mark.asyncio
    async def test_bad_call_excluded_from_success(self):
        """坏调用不计入成功序列：bad_args_recovery 只统计修正后的合法调用。"""
        from tests.agent_eval.golden_tasks import BAD_ARGS_RECOVERY_TASK

        result = await run_task(BAD_ARGS_RECOVERY_TASK)
        assert [a.name for a in result.actual_actions] == ["jd_match"]
        # 坏调用确实发生了（tool_error 在轨迹里），但被契约化回灌修正
        assert result.passed

    @pytest.mark.asyncio
    async def test_converge_on_bad_calls_terminates(self):
        """连续坏调用触发 MAX_TOOL_RETRIES 收敛：成功序列为空但正常终止。"""
        from tests.agent_eval.golden_tasks import CONVERGE_ON_BAD_CALLS_TASK

        result = await run_task(CONVERGE_ON_BAD_CALLS_TASK)
        assert result.passed
        assert result.actual_actions == []


# ═══════════════════════════════════════════════════════════════
# 确定性 + 状态哈希
# ═══════════════════════════════════════════════════════════════


class TestDeterminism:
    @pytest.mark.asyncio
    async def test_state_hash_stable_across_runs(self):
        """同任务重复运行 → 状态哈希一致（评估可复现）。"""
        from tests.agent_eval.golden_tasks import DIAGNOSE_TASK

        r1 = await run_task(DIAGNOSE_TASK)
        r2 = await run_task(DIAGNOSE_TASK)
        assert r1.state_hash == r2.state_hash
        assert r1.passed and r2.passed

    def test_state_hash_differs_on_trajectory(self):
        """状态哈希区分度：不同轨迹/回答 → 不同哈希。"""
        h1 = compute_state_hash(
            "答案A",
            [ToolCallSpec("jd_match", {"resume_id": 1})],
            {"prompt_tokens": 10, "completion_tokens": 5},
        )
        h2 = compute_state_hash(
            "答案A",
            [ToolCallSpec("jd_match", {"resume_id": 2})],
            {"prompt_tokens": 10, "completion_tokens": 5},
        )
        h3 = compute_state_hash(
            "答案B",
            [ToolCallSpec("jd_match", {"resume_id": 1})],
            {"prompt_tokens": 10, "completion_tokens": 5},
        )
        assert h1 != h2 != h3

    def test_state_hash_ignores_whitespace(self):
        """回答归一化：空白差异不改变哈希。"""
        h1 = compute_state_hash("  答案  ", [ToolCallSpec("a", {})], {})
        h2 = compute_state_hash("答案", [ToolCallSpec("a", {})], {})
        assert h1 == h2


# ═══════════════════════════════════════════════════════════════
# pass^k 公式
# ═══════════════════════════════════════════════════════════════


class TestPassAtK:
    def test_pass_at_1_is_pass_rate(self):
        """k=1 → 经验通过率 c/n。"""
        assert pass_at_k(3, 5, 1) == pytest.approx(0.6)
        assert pass_at_k(5, 5, 1) == 1.0
        assert pass_at_k(0, 5, 1) == 0.0

    def test_pass_at_2_hypergeometric(self):
        """k=2 → C(c,2)/C(n,2)。"""
        # C(3,2)/C(5,2) = 3/10
        assert pass_at_k(3, 5, 2) == pytest.approx(0.3)
        # C(4,2)/C(5,2) = 6/10
        assert pass_at_k(4, 5, 2) == pytest.approx(0.6)
        # 全过 → 1.0
        assert pass_at_k(5, 5, 2) == 1.0

    def test_pass_at_k_equals_trials(self):
        """k=n → 仅全过为 1，否则 0。"""
        assert pass_at_k(5, 5, 5) == 1.0
        assert pass_at_k(4, 5, 5) == 0.0

    def test_invalid_params(self):
        """非法参数：k>n / c<k / n<=0 → 0.0。"""
        assert pass_at_k(3, 5, 6) == 0.0
        assert pass_at_k(2, 5, 3) == 0.0
        assert pass_at_k(0, 0, 1) == 0.0
        assert pass_at_k(5, 0, 0) == 0.0


# ═══════════════════════════════════════════════════════════════
# 批量评估 + 汇总报告
# ═══════════════════════════════════════════════════════════════


class TestSuiteReport:
    @pytest.mark.asyncio
    async def test_suite_pass_at_1(self):
        """套件整体 pass@1 == 1.0（所有黄金任务通过）。"""
        reports = await run_evals(ALL_TASKS, trials=1)
        summary = summarize(reports)
        assert summary["pass_at_k"][1] == 1.0
        assert len(summary["tasks"]) == len(ALL_TASKS)
        for name, info in summary["tasks"].items():
            assert info["pass_rate"] == 1.0, f"{name} 未全过"

    @pytest.mark.asyncio
    async def test_suite_deterministic_multi_trial(self):
        """多 trial 重复运行：每任务结果一致（确定性），pass@k 稳定。"""
        reports = await run_evals(ALL_TASKS, trials=3)
        for name, results in reports.items():
            assert all(r.passed for r in results), f"{name} 第 3 次 trial 未过"
        summary = summarize(reports)
        # 全过：pass@1 = pass@2 = pass@3 = 1.0
        assert all(summary["pass_at_k"][k] == 1.0 for k in (1, 2, 3))

    @pytest.mark.asyncio
    async def test_pass_at_k_detects_failure(self):
        """pass^k 区分度：混入失败任务 → pass@2 严格小于 1。"""
        from tests.agent_eval.golden_tasks import SAVE_MEMORY_TASK
        from dataclasses import replace

        broken = replace(SAVE_MEMORY_TASK, name="broken_task", required_outputs=("永不出现",))
        reports = await run_evals((SAVE_MEMORY_TASK, broken), trials=3)
        summary = summarize(reports)
        n, c = 6, 3  # 6 trials 中 3 个通过
        assert summary["pass_at_k"][1] == pytest.approx(c / n)
        assert summary["pass_at_k"][2] == pytest.approx(pass_at_k(c, n, 2))
