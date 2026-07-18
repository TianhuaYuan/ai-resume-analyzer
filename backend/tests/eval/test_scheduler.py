"""test_scheduler — 依赖图、拓扑排序、baseline 继承、checkpoint、report 生成。"""

from __future__ import annotations

from eval.config import ExperimentConfig, PhaseConfig
from eval.executor import FakeExecutor
from eval.judge import FakeScorer
from eval.protocol import EvalDataset, TestSample
from eval.scheduler import (
    Scheduler,
    _build_dependency_graph,
    _topological_sort,
    _generate_phase_params,
)


def _mini_dataset() -> EvalDataset:
    """4 样本的迷你数据集（绕过 from_dict 的自动校验）。"""
    samples = [
        TestSample(id=f"q{i}", resume_id=1, category=cat, difficulty="easy",
                   question=f"问题{i}", reference_answer=f"答案{i}",
                   keywords=[], split="tuning", asker="hr", should_answer=sa)
        for i, (cat, sa) in enumerate([
            ("factual", True), ("reasoning", True),
            ("rejection", False), ("comparative", True),
        ])
    ]
    return EvalDataset(meta={"name": "mini"}, resumes={1: {"file": "r1.txt"}}, samples=samples)


def _mini_config() -> ExperimentConfig:
    """2 Phase：baseline(single) + scan_chunk(grid, 2 值)，baseline_params 继承。"""
    return ExperimentConfig(
        name="test_exp",
        dataset="d.json",
        strategy="grid",
        seed=42,
        baseline_params={"chunk_size": 1200, "overlap": 50, "rrf_k": 100},
        phases=[
            PhaseConfig(name="baseline", strategy="single",
                        params={"chunk_size": 1200, "overlap": 50}),
            PhaseConfig(name="scan_chunk", strategy="grid",
                        params={"chunk_size": [300, 1200]}),
        ],
    )


# ── 依赖图 ──


def test_dependency_graph_no_deps():
    cfg = _mini_config()
    graph = _build_dependency_graph(cfg)
    assert graph["baseline"] == set()
    assert graph["scan_chunk"] == set()


def test_dependency_graph_with_depends():
    cfg = ExperimentConfig(
        name="dep", dataset="d.json",
        phases=[
            PhaseConfig(name="a", params={"chunk_size": [300]}),
            PhaseConfig(name="b", depends=["a"], params={"overlap": [0]}),
            PhaseConfig(name="c", use_best_from="a", params={"rrf_k": [60]}),
        ],
    )
    graph = _build_dependency_graph(cfg)
    assert graph["a"] == set()
    assert graph["b"] == {"a"}
    assert graph["c"] == {"a"}


def test_topo_sort_order():
    graph = {"a": set(), "b": {"a"}, "c": {"a"}, "d": {"b", "c"}}
    order = _topological_sort(graph)
    assert order[0] == "a"
    assert set(order[1:3]) == {"b", "c"}
    assert order[-1] == "d"


def test_topo_sort_cycle_raises():
    graph = {"a": {"b"}, "b": {"a"}}
    try:
        _topological_sort(graph)
        assert False, "应抛 ValueError"
    except ValueError:
        pass


# ── baseline 继承 ──


def test_baseline_inheritance():
    cfg = _mini_config()
    phase = cfg.phases[1]  # scan_chunk: params={chunk_size: [300, 1200]}
    combos = _generate_phase_params(phase, cfg, best_upstream=None, seed=42)
    assert len(combos) == 2
    # chunk_size 从 grid 取，overlap 从 baseline 继承
    for p in combos:
        assert p.overlap == 50  # baseline
        assert p.rrf_k == 100   # baseline
        assert p.chunk_size in (300, 1200)


# ── Scheduler 执行 ──


async def test_run_basic():
    cfg = _mini_config()
    ds = _mini_dataset()
    sched = Scheduler(FakeExecutor(), FakeScorer(), concurrency=2)
    results = await sched.run(cfg, ds, split="tuning")
    # baseline: 1 组 + scan_chunk: 2 组 = 3 组
    assert len(results) == 3
    # 全部按 experiment_composite 降序
    ecs = [r.experiment_composite for r in results]
    assert ecs == sorted(ecs, reverse=True)
    # 每组有 4 条 entry（4 样本）
    for r in results:
        assert len(r.entries) == 4


async def test_run_to_report():
    cfg = _mini_config()
    ds = _mini_dataset()
    sched = Scheduler(FakeExecutor(), FakeScorer(), concurrency=2)
    report = await sched.run_to_report(cfg, ds, split="tuning")
    assert "experiment_composite" in report.summary
    assert len(report.per_sample) == 12  # 3 组 × 4 样本
    assert len(report.ranking) == 3
    assert report.ranking[0]["experiment_composite"] >= report.ranking[-1]["experiment_composite"]


# ── checkpoint ──


async def test_checkpoint_skip(tmp_path):
    cfg = _mini_config()
    ds = _mini_dataset()
    ckpt_dir = tmp_path / "ckpt"

    # 第一次运行：生成 checkpoint
    sched1 = Scheduler(FakeExecutor(), FakeScorer(), concurrency=2, checkpoint_dir=ckpt_dir)
    results1 = await sched1.run(cfg, ds, split="tuning")
    assert len(results1) == 3

    # checkpoint 文件存在
    ckpt_files = list(ckpt_dir.rglob("*.json"))
    assert len(ckpt_files) == 3

    # 第二次运行：应跳过（从 checkpoint 加载）
    sched2 = Scheduler(FakeExecutor(), FakeScorer(), concurrency=2, checkpoint_dir=ckpt_dir)
    results2 = await sched2.run(cfg, ds, split="tuning")
    assert len(results2) == 3
    # experiment_composite 应与第一次一致
    for r1, r2 in zip(results1, results2):
        assert abs(r1.experiment_composite - r2.experiment_composite) < 1e-9


# ── use_best_from ──


async def test_use_best_from():
    cfg = ExperimentConfig(
        name="chain", dataset="d.json", strategy="grid", seed=42,
        baseline_params={"chunk_size": 1200, "overlap": 50, "rrf_k": 100,
                         "dense_top_k": 20, "sparse_top_k": 20, "hybrid_top_k": 20,
                         "rerank_input_top_k": 20, "rerank_final_top_k": 5,
                         "rerank_truncation": 400, "reject_threshold": 0.3,
                         "generate_temperature": 0.3},
        phases=[
            PhaseConfig(name="phase_a", strategy="grid",
                        params={"chunk_size": [300, 1200]}),
            PhaseConfig(name="phase_b", use_best_from="phase_a",
                        params={"overlap": [0, 50]}),
        ],
    )
    ds = _mini_dataset()
    sched = Scheduler(FakeExecutor(), FakeScorer(), concurrency=2)
    results = await sched.run(cfg, ds, split="tuning")
    # phase_a: 2 组 + phase_b: 2 组 = 4 组
    assert len(results) == 4
