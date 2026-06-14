# MonkeyAgent 全功能回归测试用例

本文档用于沉淀 MonkeyAgent 的产品级回归清单。默认回归不依赖真实公网、真实 Telegram、真实飞书或真实百炼；真实外部调用只作为 optional smoke。

## 默认回归命令

```bash
python3 -m compileall monkey_agent tests
python3 -m unittest discover -s tests
python3 -m monkey_agent quickstart
python3 -m monkey_agent doctor
```

如果终端出现 `fnm_multishells` symlink 权限提示，但 Python 命令退出码为 0，不视为 MonkeyAgent 失败。

## Ask / Routing

| 类型 | 前置条件 | 输入 | 预期 |
|---|---|---|---|
| automated | 基础规则已加载 | `1+1等于几` | route=`rules`，答案包含 `2`，生成 run |
| automated | 基础规则已加载 | `5乘以5等于多少` | route=`rules`，答案包含 `25`，生成 run |
| automated | 基础规则已加载 | `明天是几号` | route=`rules`，答案非空 |
| automated | 本地模型 fallback | `水为什么会结冰` | route=`general_reason`，不进入 `need_more_info` |
| automated | 本地模型 fallback | `介绍你自己，说明你的能力` | route=`general_reason`，答案说明 MonkeyAgent 能力 |
| automated | 本地模型 fallback | `你用到LangGraph、Harness Engineering哪些内容？怎么应用的` | route=`general_reason`，答案包含 LangGraph / Goal / 确认机制 |
| automated | 无文件、无字段、无分析目标 | `分析一下这个数据` | 允许 route=`need_more_info` |

## Weather / Tools

| 类型 | 前置条件 | 输入 | 预期 |
|---|---|---|---|
| automated | fake weather tool | `看下明天上海的天气` | 调用天气能力，答案包含上海和天气结果 |
| automated | 默认地点=`上海` | `看下明天的天气` | 使用默认地点，不要求补充地点 |
| automated | failing weather tool | `看下明天上海的天气` | 不编造天气，evaluation 标记工具失败已披露 |
| automated | fake web search / 无天气误命中 | `明天NBA有哪些比赛` | 不命中天气规则，不误用日期规则 |

## Skills

| 类型 | 前置条件 | 输入 | 预期 |
|---|---|---|---|
| automated | YAML Skill 已写入 | `帮我写一个周报结构` | 命中 YAML Skill 或已审核全局规则，不返回通用澄清模板 |
| automated | 导入合法 Agent Skill | `帮我创建 browser automation pytest 测试方案` | route=`skills`，`skill_kind=agent` |
| automated | Agent Skill 带脚本 | `请执行 script skill tasks` | 未确认时不执行，返回 `requires_confirmation=true` |
| automated | Agent Skill 带安全脚本 | 上一条 + `confirm_skill_execution=true` | 执行成功，返回 stdout/artifacts |
| automated | Agent Skill 危险脚本 | `skills run unsafe --confirm` | 被安全检查拒绝 |

## Self-learning / Review

| 类型 | 前置条件 | 输入 | 预期 |
|---|---|---|---|
| automated | 无 | `以后默认用表格输出` | 生成 Memory 或 pending candidate |
| automated | 已有 pending | `采用刚才那个` | approve latest pending |
| automated | 已有 pending | `记住这个` | approve latest pending |
| automated | 已有 pending | `不要沉淀` | reject latest pending |
| automated | 已有 pending | `这个规则不对` | reject latest pending |
| automated | 普通常识问答 | `水为什么会结冰` | 不强制生成 Rule/Skill |

## Goal Engine

| 类型 | 前置条件 | 输入 | 预期 |
|---|---|---|---|
| automated | 本地模型 fallback | `goal start "我作为销售明天拜访甲方，帮我准备行动方案"` | 创建 goal、tasks、run |
| automated | 已创建 goal | `goal step <goal_id>` | 推进任务，写 events/evaluations |
| automated | 删除 projection 文件 | `goal status/step <goal_id>` | 可从 checkpoint/projection 恢复 |
| automated | 飞书发送类目标 | `goal step` | 进入 `waiting_human`，未 confirm 不执行副作用 |
| automated | 上一条 + confirm | `goal step <goal_id> --confirm` | 继续执行并完成 |

## Run Trace / Diagnose

| 类型 | 前置条件 | 输入 | 预期 |
|---|---|---|---|
| automated | 任意 ask | `agent.ask(...)` | 返回 `run_id` |
| automated | 已有 ask run | `runs latest --type ask` | 返回最近 Ask run |
| automated | 已有 run | `diagnose latest` | 输出问题、route、慢节点、工具失败、建议 |
| automated | Tool Builder 失败 | `帮我生成一个危险查询工具` | tool run 不保存完整生成代码正文 |

## CLI / Setup / Doctor

| 类型 | 前置条件 | 输入 | 预期 |
|---|---|---|---|
| automated | 无 API Key | `doctor` | `DASHSCOPE_API_KEY` 为 WARN，不失败 |
| automated | 临时目录 | `setup location --location 上海` | 写入默认地点，不覆盖其他 `.env` 配置 |
| automated | 本地 fake 能力 | `quickstart` | 10 项 PASS |
| automated | 任意 ask | `ask` | 默认只输出自然语言 |
| automated | 任意 ask | `ask --trace` | 输出路由摘要 |
| automated | 任意 ask | `ask --debug` | 输出完整 JSON |

## Telegram

| 类型 | 前置条件 | 输入 | 预期 |
|---|---|---|---|
| automated | setup mode | `/whoami` | 返回 chat_id |
| automated | setup mode | 普通文本 | 不调用 Agent，提示配置白名单 |
| automated | 白名单 chat | `1+1等于几` | 调用 Agent 并回复答案 |
| automated | 白名单 chat | `/help` | 返回能力说明 |
| automated | 白名单 chat | `/status` | 返回授权、默认地点、最近 run |
| automated | 白名单 chat | `/settings` | 返回默认地点、chat_id、trace 状态 |
| automated | 白名单 chat | `/trace on/off` | 控制是否追加 route/run_id |
| automated | 白名单 chat | 非文本消息 | 返回“当前仅支持文本消息” |
| manual | 已配置真实 Bot | `python3 -m monkey_agent telegram start` | Telegram 私聊可正常问答 |

## Optional Smoke

这些测试依赖真实外部环境，不进入默认回归：

```bash
python3 -m monkey_agent model smoke --role chat
python3 -m monkey_agent model smoke --role classifier
python3 -m monkey_agent telegram start
```

真实 Telegram smoke 建议发送：

```text
/help
/status
5乘以5等于多少
看下明天的天气
介绍你自己，说明你的能力
```
