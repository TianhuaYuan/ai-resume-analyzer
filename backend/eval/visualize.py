"""
可视化 Baseline 对照实验结果。
用法: python -m eval.visualize
输出: backend/eval/baseline_charts.png
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

RESULTS_PATH = Path(__file__).parent / "baseline_results.json"
OUTPUT_PATH = Path(__file__).parent / "baseline_charts.png"

# ── 加载数据 ────────────────────────────────────────────────

with open(RESULTS_PATH, encoding="utf-8") as f:
    data = json.load(f)

exp_names = list(data.keys())
metrics_keys = [
    "Recall@3", "Recall@5", "Recall@10",
    "MRR", "Precision@5",
    "answer_hit_rate", "reject_accuracy",
]

# 提取数值
rows = {}
for exp, info in data.items():
    m = info["metrics"]
    rows[exp] = {k: float(m[k]) for k in metrics_keys if k in m}

# ── 图表 ────────────────────────────────────────────────────

plt.rcParams.update({
    "font.family": "Microsoft YaHei",
    "font.size": 10,
    "axes.unicode_minus": False,
})

fig, axes = plt.subplots(1, 2, figsize=(16, 6))
fig.suptitle("RAG Baseline 对照实验（50 条 Golden Set）", fontsize=14, fontweight="bold", y=1.02)

colors = ["#4472C4", "#ED7D31", "#A5A5A5", "#FFC000"]

# ── 左图：检索指标分组柱状图 ──────────────────────────────

retrieval_keys = ["Recall@3", "Recall@5", "Recall@10", "MRR", "Precision@5"]
short_labels = ["R@3", "R@5", "R@10", "MRR", "P@5"]

ax = axes[0]
x = np.arange(len(retrieval_keys))
width = 0.2

for i, name in enumerate(exp_names):
    values = [rows[name].get(k, 0) for k in retrieval_keys]
    bars = ax.bar(x + i * width, values, width, label=name[:2] + name[-4:], color=colors[i])
    for bar, v in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.015,
                f"{v:.3f}", ha="center", fontsize=7)

ax.set_xticks(x + width * 1.5)
ax.set_xticklabels(short_labels, fontsize=11)
ax.set_ylim(0, 1.15)
ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1, decimals=0))
ax.set_title("检索指标对比", fontsize=12, fontweight="bold")
ax.legend(loc="lower right", fontsize=8)
ax.grid(axis="y", alpha=0.3)

# ── 右图：进化趋势折线图 ──────────────────────────────────

ax2 = axes[1]
for i, key in enumerate(retrieval_keys):
    values = [rows[name].get(key, 0) for name in exp_names]
    ax2.plot(range(4), values, marker="o", label=short_labels[i],
            color=plt.cm.viridis(i / len(retrieval_keys)), linewidth=2, markersize=6)

# 标注最大值
for i, key in enumerate(retrieval_keys):
    values = [rows[name].get(key, 0) for name in exp_names]
    best_idx = np.argmax(values)
    ax2.annotate(f"{values[best_idx]:.3f}", (best_idx, values[best_idx]),
                textcoords="offset points", xytext=(0, 10), ha="center", fontsize=7,
                color=plt.cm.viridis(i / len(retrieval_keys)))

ax2.set_xticks(range(4))
ax2.set_xticklabels(["①纯向量", "②+BM25", "③+Rerank", "④+改写"], fontsize=10)
ax2.set_ylim(0, 1.15)
ax2.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1, decimals=0))
ax2.set_title("各指标随实验组进化趋势", fontsize=12, fontweight="bold")
ax2.legend(loc="lower right", fontsize=7, ncol=2)
ax2.grid(True, alpha=0.3)

# 标注 Rerank 跳跃
ax2.annotate("Rerank 最大提升点",
            xy=(2, 0.929), xytext=(1.5, 1.05),
            arrowprops=dict(arrowstyle="->", color="red", lw=1.5),
            fontsize=9, color="red", fontweight="bold")

plt.tight_layout()
plt.savefig(OUTPUT_PATH, dpi=150, bbox_inches="tight", facecolor="white")
print(f"图表已保存: {OUTPUT_PATH}")
plt.close()
