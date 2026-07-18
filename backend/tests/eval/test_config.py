"""test_config — YAML 加载、网格组合计数、校验、bayes 行为。"""

from __future__ import annotations

import textwrap

import pytest

from core.rag_params import RagParams
from eval.config import (
    ExperimentConfig,
    PhaseConfig,
    generate_parameter_combinations,
    load_config,
    validate_config,
)


def _write(tmp_path, text: str) -> str:
    p = tmp_path / "cfg.yaml"
    p.write_text(textwrap.dedent(text), encoding="utf-8")
    return str(p)


def test_load_config_grid_count(tmp_path):
    path = _write(tmp_path, """
        name: grid_demo
        dataset: ../eval_data/golden_set_v2.json
        strategy: grid
        phases:
          - name: chunk
            description: 分块扫描
            strategy: grid
            parameters:
              chunk_size: [300, 500, 800, 1200]
              overlap: [0, 50]
    """)
    cfg = load_config(path)
    assert isinstance(cfg, ExperimentConfig)
    assert cfg.strategy == "grid"
    assert len(cfg.phases) == 1

    combos = generate_parameter_combinations(cfg, "grid")
    # 4 * 2 = 8 组合
    assert len(combos) == 8
    assert all(isinstance(c, RagParams) for c in combos)
    # 全部合法
    assert all(not c.validate() for c in combos)


def test_load_config_single(tmp_path):
    path = _write(tmp_path, """
        name: single_demo
        dataset: d.json
        phases:
          - name: smoke
            strategy: single
            parameters:
              chunk_size: 800
              overlap: 50
    """)
    cfg = load_config(path)
    combos = generate_parameter_combinations(cfg, "single")
    assert len(combos) == 1
    assert combos[0].chunk_size == 800
    assert combos[0].overlap == 50


def test_load_config_repeated(tmp_path):
    path = _write(tmp_path, """
        name: repeat_demo
        dataset: d.json
        phases:
          - name: verify
            strategy: repeated
            repeat: 3
            parameters:
              chunk_size: 800
    """)
    cfg = load_config(path)
    combos = generate_parameter_combinations(cfg, "repeated")
    assert len(combos) == 3
    assert all(c.chunk_size == 800 for c in combos)


def test_validate_rejects_invalid_param_key(tmp_path):
    path = _write(tmp_path, """
        name: bad
        dataset: d.json
        phases:
          - name: p
            parameters:
              not_a_real_field: [1, 2]
    """)
    cfg = load_config(path)
    errs = validate_config(cfg)
    assert any("not_a_real_field" in e for e in errs)
    # 生成时该非法键会导致构造失败 → 组合被丢弃
    combos = generate_parameter_combinations(cfg, "grid")
    assert combos == []


def test_validate_depends_and_use_best_from(tmp_path):
    path = _write(tmp_path, """
        name: dep
        dataset: d.json
        phases:
          - name: a
            parameters: {chunk_size: [300]}
          - name: b
            depends: [a]
            use_best_from: a
            parameters: {overlap: [0]}
          - name: c
            depends: [ghost]
            parameters: {overlap: [0]}
    """)
    cfg = load_config(path)
    errs = validate_config(cfg)
    assert any("ghost" in e for e in errs)


def test_bayes_returns_combos(tmp_path):
    path = _write(tmp_path, """
        name: bayes_demo
        dataset: d.json
        phases:
          - name: opt
            strategy: bayes
            max_trials: 8
            parameters:
              chunk_size: [300, 500, 800, 1200]
              overlap: [0, 50, 100]
    """)
    cfg = load_config(path)
    combos = generate_parameter_combinations(cfg, "bayes")
    assert len(combos) == 8
    assert all(isinstance(c, RagParams) for c in combos)
    # 采样结果应落在给定候选范围内
    for c in combos:
        assert c.chunk_size in {300, 500, 800, 1200}
        assert c.overlap in {0, 50, 100}


def test_bayes_raises_without_optuna(monkeypatch):
    # 模拟 optuna 未安装 → 调用时抛 NotImplementedError
    cfg = ExperimentConfig(
        name="x", dataset="d.json",
        phases=[PhaseConfig(name="p", strategy="bayes", params={"chunk_size": [300, 500]})],
    )
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "optuna" or name.startswith("optuna."):
            raise ImportError("no optuna")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(NotImplementedError):
        generate_parameter_combinations(cfg, "bayes")
