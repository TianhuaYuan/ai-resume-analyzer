"""A3 Agent 评估框架（黄金任务 + 状态哈希 + pass^k）。

（黄金指令/动作/输出三元组 + pass^k 超几何公式）与
pydantic-ai TestModel 设计对齐。

设计要点：
- 确定性：mock LLM 按脚本驱动 agent 轨迹，无真实 LLM 调用 → CI 稳定可回归
- 黄金任务 = {instruction, script(注入的假模型响应), gold_actions(期望成功工具序列),
  required_outputs(最终回答必须包含)}——script 可注入坏调用（参数缺失/未知工具）验证
  契约化回灌与收敛行为
- 状态哈希：每次运行计算"规范化状态指纹"（成功轨迹 + 最终回答 + token），供审计与回归比对
- pass^k：C(c,k)/C(n,k)，任务池整体质量报告（k 次抽样全过的概率）
"""
