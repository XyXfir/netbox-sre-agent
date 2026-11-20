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
| GitHub 推送 | 已完成，仓库 https://github.com/XyXfir/netbox-sre-agent（经 Git Data API 推送，git push 因网络不通） |
| 真实 LLM 验证 | 已完成，glm-5 跑通，见 `examples/live_trace.txt` |
| 单测 | 20 项全过（含回滚/剧本/告警） |
| 行为评估集 | 4/4 场景、20/20 断言 |

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

**步骤 4 — 可选增强（全部完成）**
- 回滚工具：`rollback_ip_status` 依据审计日志 before 值恢复，回滚留痕并纳入护栏。（`tests/test_rollback.py` 4 项通过）
- Playbook 目录化：`playbooks/*.json` 三种剧本，`get_playbook(signal)` 按信号路由。（`tests/test_playbook.py` 8 项通过）
- 告警驱动：`run_alert.py` 把 Alertmanager payload 转 goal，取 firing + 指纹去重。（`tests/test_alerting.py` 4 项通过）
- 评估集：`eval/agent_eval.py`，4/4 场景、20/20 断言通过。

**步骤 5 — 收尾**
- 清理中间产物，只保留最终文件。
- README 补上真实运行截图/输出与仓库链接。

## 验收标准

- `python run_demo.py` 退出码 0，报告 `resolved: true`。
- `python -m unittest discover -s tests -v` 4 项全过。
- `DRY_RUN=true` 时 NetBox 数据零变更。
- 每次写操作都有 journal 记录。
- GitHub 仓库链接可正常访问。
