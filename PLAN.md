# 执行计划

## 目标

按笔试要求，交付一个基于 netbox-docker 的工具调用 Agent：实现至少一个完整工作闭环（发现异常 → 分析诊断 → 提出处置建议 → 执行处置 → 验证），代码提交到 GitHub，README 写明设计思路、运行方式和效果演示。

## 当前状态

| 项 | 状态 |
|---|---|
| 原型代码（Agent / 工具 / 双后端） | 已完成 |
| 离线演示 `run_demo.py` | 已完成，5 步闭环 |
| 单测 `tests/test_agent.py` | 已完成，4 项通过 |
| README | 已完成 |
| GitHub 推送 | 未完成，网络返回 502 |
| 真实 LLM 验证 | 未完成，缺 Key |

## 待确认输入

1. 是否要真实 LLM 演示；要则提供 LLM Base URL / API Key / 模型名，以及一个可用的 NetBox 地址。
2. GitHub 仓库公开还是私有。
3. GitHub 访问是否正常；不正常则提供可用 Git 远端。

## 执行步骤

**步骤 1 — 解除阻塞**
- 拿到上面三个确认项，更新 `.env`。

**步骤 2 — 真实 LLM 端到端验证**
- `DRY_RUN=true` 运行 `run_live.py`，检查工具调用序列是否合理。
- 确认无误后改为 `DRY_RUN=false`，验证写操作真实生效且可复核。
- 记录一次真实输出到 `examples/live_output.txt`。

**步骤 3 — GitHub 提交**
- 在 GitHub 创建空仓库（不勾选 README）。
- `git remote add origin <url>` → `git push -u origin main`。
- 验证链接可访问，把地址发给面试官。

**步骤 4 — 可选增强**
- 告警驱动：Alertmanager webhook 把告警事件转成 Agent 的 goal。（待做）
- 回滚工具：依据审计日志的 before 值恢复变更。（待做）
- Playbook 目录化：处置策略抽成可插拔文件，按异常类型路由。（待做）
- 评估集：检验工具序列正确性、是否误触发写操作、是否漏掉验证，输出通过率。（**已完成**：`eval/agent_eval.py`，4/4 场景、20/20 断言通过）

**步骤 5 — 收尾**
- 清理中间产物，只保留最终文件。
- README 补上真实运行截图/输出与仓库链接。

## 验收标准

- `python run_demo.py` 退出码 0，报告 `resolved: true`。
- `python -m unittest discover -s tests -v` 4 项全过。
- `DRY_RUN=true` 时 NetBox 数据零变更。
- 每次写操作都有 journal 记录。
- GitHub 仓库链接可正常访问。
