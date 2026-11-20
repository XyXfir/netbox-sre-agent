# NetBox SRE Agent — 具备真实 Tool Calling 的运维闭环 Agent

以 [netbox-docker](https://github.com/netbox-community/netbox-docker) 为运维对象，实现一个通过 **function calling / tool calling** 驱动的 SRE Agent，完成 **发现异常 → 分析诊断 → 提出处置建议 → 执行处置 → 验证恢复** 的完整闭环。

核心观点：**Agent 只是编排层，SRE 价值在闭环本身**。所以这个项目的重点不是模型多聪明，而是工具边界清晰、写操作可审计、可 dry-run、执行后必须验证。

---

## 1. 与 SRE 岗位的关联

| 题目要素 | 对应的 SRE 能力 |
| --- | --- |
| NetBox / IPAM / DCIM | 基础设施资产管理、地址规划、变更源头 |
| Docker 容器状态与日志 | 可观测性、故障定位 |
| 发现异常 | 监控巡检、告警降噪 |
| 分析诊断 | 根因分析、排除法（先看对象属性，再看容器日志） |
| 处置建议 | Runbook / 变更方案 / 风险评估 |
| 执行处置 | 自动化（toil reduction）、幂等操作 |
| 验证与审计 | 闭环确认、变更追溯、回滚依据 |

短板也很明确：这题同时考 AI 工程。面试时应主动把叙事落在 **「自动化运维的可靠性」**——白名单、dry-run、journal 审计、写后验证、高风险动作只建议不执行——而不是停留在「我接了个大模型」。

---

## 2. 场景设计

**异常场景：NetBox IPAM 中出现重复 IP 记录 + 地址段容量告警。**

1. **发现**：`get_system_health` 检查 NetBox API 与容器；`list_prefixes(min_utilization=85)` 找出 `10.42.7.0/24` 利用率 94%；`list_ip_addresses(duplicate_only=True)` 找出 `10.42.7.15/24` 被记录两次。
2. **诊断**：`get_ip_address(102)` 显示该记录无归属设备、无描述、创建时间较晚；另一条绑定在 `web-01`。`get_container_logs("netbox")` 无报错，排除服务自身故障 → 判定为**人工变更后未回收的孤立 IP 记录**。
3. **建议**：低风险动作（置为 `reserved`、打标签、写 journal）自动执行；前缀扩容属于地址规划，**只输出建议，不自动变更**。
4. **执行**：调用 3 个写工具，全部进入审计日志。
5. **验证**：`verify_remediation` 重新计算该地址的 active 记录数，确认从 2 降到 1。

---

## 3. 技术架构

```
用户目标
   │
   ▼
┌──────────────────────────────────────────────┐
│ SREAgent (app/agent.py)                      │
│  system prompt + 对话历史 + tool_calls 循环   │
└───────────────┬──────────────────────────────┘
                │ tools=[11 个 OpenAI 格式 schema]
                ▼
┌──────────────────────────────────────────────┐
│ LLM 适配器 (app/llm.py)                       │
│  OpenAICompatLLM  ← 真 function calling       │
│  MockLLM          ← 离线协议兼容模拟           │
└───────────────┬──────────────────────────────┘
                │ name + arguments
                ▼
┌──────────────────────────────────────────────┐
│ ToolRegistry (app/tools.py)                  │
│  白名单 / dry-run / 异常转文本 / 审计日志       │
└───────────────┬──────────────────────────────┘
                │ 统一方法名
        ┌───────┴────────┐
        ▼                ▼
  MockBackend       NetBoxBackend
  (内存，带种子异常)   (NetBox REST + docker CLI)
```

关键点：**Mock 与 Live 共用同一个 Agent 循环和同一套工具 schema**，离线演示不是另一套假流程，而是同一条流水线的可验证替身。

---

## 4. 快速开始

### 环境

- Python 3.9+（开发环境 3.13）
- 仅一个第三方依赖：`requests`

```bash
pip install -r requirements.txt
```

### A. 离线演示（不需要 API Key / NetBox / Docker）

```bash
python run_demo.py
```

会打印 9 次工具调用、诊断推理、最终五段式报告和 3 条审计记录，并在断言失败时退出非零码。

回归测试：

```bash
python -m unittest discover -s tests -v
```

行为评估集（数据驱动的 4 个场景：完整闭环 / dry-run 拦截 / 白名单收紧 / 干净环境不误写）：

```bash
python eval/agent_eval.py
```

当前结果：**4/4 场景通过，20/20 断言通过（100%）**。它验证的不只是"跑通"，而是工具序列正确性、无异常时不误触发写操作、以及护栏是否真的拦住了写操作。

### B. 真实模式（真实 function calling）

```bash
cp .env.example .env
# 填写 NETBOX_URL / NETBOX_TOKEN / LLM_BASE_URL / LLM_API_KEY / LLM_MODEL
python run_live.py
```

- `NETBOX_URL` 例如 `http://localhost:8000`（netbox-docker 默认映射端口）。
- Token 在 NetBox Web UI 中创建，需具备 IPAM 读写与 extras 写权限。
- `LLM_BASE_URL` 任意 OpenAI 兼容端点即可（DashScope / OpenAI / DeepSeek / vLLM / Ollama）。
- **先保持 `DRY_RUN=true`**：此时所有写工具被 registry 拦截，只打印计划，不改 NetBox。确认计划合理后再改为 `false`。

---

## 5. 工具清单

| 工具 | 类型 | 用途 |
| --- | --- | --- |
| `get_system_health` | 读 | NetBox API 可达性 + Docker 容器状态 |
| `list_prefixes` | 读 | 按利用率筛前缀 |
| `list_ip_addresses` | 读 | 查重复 IP / 按状态筛选 |
| `get_ip_address` | 读 | 单条 IP 完整属性 |
| `list_devices` | 读 | 设备清单 |
| `get_container_logs` | 读 | 容器日志尾部 |
| `update_ip_status` | **写** | 修改 IP 状态（如 stale → reserved） |
| `add_ip_tag` | **写** | 打标签便于追溯 |
| `create_journal_entry` | **写** | 写 NetBox journal，形成审计链 |
| `verify_remediation` | 读 | 写后复核，异常是否真的消失 |
| `restart_container` | **写** | 重启容器（仅在日志有证据时；默认提示不自动执行） |

---

## 6. 效果演示（摘自 `python run_demo.py` 真实输出）

```
[step 1] TOOL CALL  list_ip_addresses({"duplicate_only": true})
          RESULT : {"ok": true, "data": [{"id": 101, "address": "10.42.7.15/24",
                   "assigned_object": "web-01", ...}, {"id": 102, "address":
                   "10.42.7.15/24", "assigned_object": null, ...}]}

[step 2] TOOL CALL  get_ip_address({"ip_id": 102})
          RESULT : {"ok": true, "data": {"id": 102, "address": "10.42.7.15/24",
                   "status": "active", "assigned_object": null, "description": ""}}

[step 3] TOOL CALL  update_ip_status({"ip_id": 102, "status": "reserved"})
          REASONING: 诊断：10.42.7.15/24 存在两条 active 记录；id=102 无归属设备、
                     无描述，判定为过期/孤立记录。netbox 容器日志无异常。
                     建议：置为 reserved、打标签、写 journal；前缀扩容需变更评审。

[step 4] TOOL CALL  verify_remediation({"check": "duplicate_address",
                                       "address": "10.42.7.15/24"})
          RESULT : {"ok": true, "data": {"active_count": 1, "resolved": true}}

[step 5] FINAL ANSWER
【SRE 巡检闭环报告】
发现：容器 4/4 健康；高危前缀 10.42.7.0/24 利用率 94.0%；重复地址 10.42.7.15/24。
诊断：孤立 IP id=102 无归属、无描述，容器日志正常，判定为陈旧 IPAM 记录。
建议：已按低风险策略处置；前缀扩容需变更评审，未自动执行。
执行：status -> reserved、添加 sre-agent-triage 标签、写入 NetBox journal。
验证：冲突是否解除 = True；审计记录已写入 tool registry。

PASS: closed loop finished in 5 steps, 3 audit records written.
```

完整输出见 `examples/demo_output.txt`。

---

## 7. 安全设计

- **写工具白名单**：`allowed_write_tools` 可单独收窄权限。
- **dry-run 开关**：所有写工具在 registry 层被拦截，不依赖模型自觉。
- **先读后写**：提示词强制要求写操作必须有前序读数据支撑。
- **审计日志**：每次写操作记录 tool / args / result（含 before → after）。
- **写后验证**：`verify_remediation` 是闭环的强制步骤。
- **高风险不自动化**：地址段扩容、删除对象、重启生产容器只给建议。
- **工具异常转文本**：工具报错作为 `role=tool` 消息回灌给模型，不会击穿主循环。

---

## 8. 局限与扩展方向

**当前局限（坦诚说明）**

- MockLLM 是基于工具输出做决策的**规则式模拟器**，不是语言模型；它用于证明 Tool Calling 管线和闭环可执行，真正的自然语言推理在 `run_live.py`。
- 目前只做了一个场景（重复 IP + 容量告警）。
- `restart_container` 已定义但演示中不触发，避免把「重启生产容器」做成默认动作。
- NetBox API 不同版本字段略有差异，`list_prefixes` 在缺少 `utilization` 字段时会退化为估算。

**可扩展**

- 接入 Prometheus / Alertmanager，由告警事件触发 Agent。
- 增加变更工单工具（创建 Jira / 飞书审批），形成「建议 → 审批 → 执行」两段式。
- 回滚工具：根据审计日志把 status 恢复到 before 值。
- 把 runbook 做成可插拔的 playbook 目录，按异常类型路由。

---

## 9. 目录结构

```
netbox-sre-agent/
├── app/
│   ├── agent.py       # Tool Calling 主循环
│   ├── backends.py    # MockBackend / NetBoxBackend
│   ├── llm.py         # OpenAI 兼容客户端 + MockLLM
│   ├── prompt.py      # SRE 系统提示词
│   └── tools.py       # 工具 schema、registry、guardrails
├── examples/demo_output.txt
├── eval/agent_eval.py # 行为评估集
├── tests/test_agent.py
├── run_demo.py        # 离线入口
├── run_live.py        # 真实入口
├── requirements.txt
└── .env.example
```
