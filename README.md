# MonkeyAgent

MonkeyAgent is a single-person, rules-first, self-learning personal assistant
Agent for SmartAgentOS-style workflows.

It is designed to be deployed by one person as a private assistant, not as a
multi-tenant SaaS service. MonkeyAgent helps with everyday work such as preparing
customer visits, writing reports, summarizing meetings, querying live
information, creating Feishu/Lark message automations, remembering preferred
formats, and turning repeated corrections into reviewed personal Rules or
Skills.

The core idea is simple: stable knowledge should become deterministic, personal
habits should become memory, reusable methods should become Skills, and risky or
uncertain actions should ask for confirmation instead of guessing.

Execution priority is fixed:

```text
deterministic Rules/tools -> semi-deterministic RAG/history/Skills -> LLM reasoning with human confirmation -> learning deposits
```

## What MonkeyAgent Feels Like

MonkeyAgent is meant to behave less like a one-shot chatbot and more like a
personal operating layer:

- **Ask for advice**: “我作为乙方软件公司的销售，明天要去拜访甲方，我应该准备什么？”
  MonkeyAgent gives a practical preparation checklist first, then asks for
  missing context only where it matters.
- **Use settled rules first**: “已完成 10，总数 200，完成率是多少？”
  If a percentage Rule exists, MonkeyAgent computes the exact result and the LLM
  cannot override it.
- **Remember preferences**: “以后默认用表格输出。”
  The preference goes through pending review and, once adopted, later answers use
  that format automatically.
- **Explore missing capabilities**: “今天上海天气怎么样？”
  If a weather tool is available, it uses the tool. If a stable tool gap is
  detected, it can generate a reviewed candidate capability instead of inventing
  weather.
- **Work toward goals**: “帮我接入飞书机器人，支持给指定群发送消息。”
  The Goal Engine decomposes the goal, explores docs/tools, runs safe dry-runs,
  waits for confirmation before external writes, and records the trace.
- **Explain itself**: every Ask, Goal, and Tool Builder attempt writes a Run
  record so you can inspect why MonkeyAgent routed the request a certain way.

## Install

```bash
cd MonkeyAgent
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Set `DASHSCOPE_API_KEY` in `.env` to use Alibaba Cloud Bailian / DashScope models.

For Bailian specifically:

```bash
cp .env.bailian.example .env
# edit .env and fill DASHSCOPE_API_KEY
```

## CLI

```bash
monkey ask "我作为乙方软件公司的销售，明天要去拜访甲方，我应该准备什么？"
monkey ask "帮我总结今天的会议纪要，并输出行动项"
monkey ask "以后默认用表格输出，这是我的偏好"
monkey ask "今天上海天气怎么样？"
monkey rules list
monkey skills list --type all
monkey skills install vercel-labs/skills --skill find-skills
monkey skills install vercel-labs/skills/find-skills
monkey skills import /path/to/skill-dir
monkey skills inspect find-skills
monkey skills disable find-skills
monkey skills enable find-skills
monkey skills remove find-skills
monkey memory list
monkey counterexamples list
monkey capabilities list
monkey tools list
monkey tools generated list
monkey tools generated inspect <tool-id>
monkey tools generated test <tool-id>
monkey tools generated enable <tool-id>
monkey tools generated disable <tool-id>
monkey goal start "帮我接入飞书机器人发送消息"
monkey goal step <goal-id>
monkey goal plan <goal-id>
monkey goal events <goal-id>
monkey goal pause <goal-id>
monkey goal resume <goal-id>
monkey runs list
monkey runs latest --type ask
monkey runs inspect <run-id>
monkey review list
monkey review approve <candidate-id>
monkey adopt <candidate-id>
monkey serve --port 8000
```

## Personal Assistant Scenarios

### 1. Sales visit preparation

```bash
python3 -m monkey_agent ask "我作为乙方软件公司的销售，明天要去拜访甲方，我应该准备什么？"
```

Expected behavior:

- Classifies the request as personal/sales support rather than a calculation or
  API task.
- Gives a usable preparation plan: customer background, pain-point hypothesis,
  agenda, discovery questions, materials, objection handling, and next-step
  follow-up.
- Does not force a generic “字段定义 / API / 数据源” clarification template.
- May ask focused follow-up questions such as industry, product, meeting role,
  and visit objective.

### 2. Meeting note assistant

```bash
python3 -m monkey_agent ask "帮我把这段会议纪要整理成摘要、决策、待办和风险"
```

Expected behavior:

- Uses YAML Skills or Agent Skills if a meeting-summary Skill is installed.
- Applies personal memory such as “默认表格输出” after the preference is adopted.
- If the meeting content is missing, asks for the transcript or notes instead of
  fabricating decisions.

### 3. Rules-first deterministic work

```bash
python3 -m monkey_agent ask "已完成10，总数200，完成率百分比是多少？" --context '{"numerator":10,"denominator":200}'
```

Expected behavior:

- Hits the settled percentage Rule first.
- Returns `5.00%`.
- Records in Evaluation that the deterministic Rule value was used.

### 4. Personal memory and adoption

```bash
python3 -m monkey_agent ask "以后默认用表格输出，这是我的偏好"
python3 -m monkey_agent review list
python3 -m monkey_agent ask "同意沉淀"
python3 -m monkey_agent ask "帮我写一份项目周报"
```

Expected behavior:

- The first request creates a pending Memory candidate.
- `同意沉淀` promotes it into the personal workspace.
- Later report-style answers prefer a table format.

### 5. Live information and reusable capabilities

```bash
python3 -m monkey_agent ask "今天上海天气怎么样？"
python3 -m monkey_agent ask "明天合肥天气怎么样？"
```

Expected behavior:

- Uses the built-in weather capability when available.
- If MonkeyAgent has to create a generated tool candidate, the learned ability is
  generalized as “weather query capability”, not “today Shanghai only”.
- Similar future weather questions should reuse the settled/generated capability
  instead of rebuilding from scratch.

### 6. Goal-driven assistant work

```bash
python3 -m monkey_agent goal start "帮我接入飞书机器人，支持给指定群发送消息，并沉淀成可复用能力。" --max-steps 5
python3 -m monkey_agent goal step <goal-id>
python3 -m monkey_agent goal events <goal-id>
python3 -m monkey_agent runs latest --type goal
```

Expected behavior:

- Decomposes the objective into a small task DAG.
- Automatically performs safe planning, research, dry-run, and candidate
  generation.
- Stops at `waiting_human` before real external writes such as sending a Feishu
  message.
- Stores events, evidence, evaluations, and a Run Trace for review.

## Bailian Test

After filling `.env`:

```bash
python3 -m monkey_agent model smoke
python3 -m monkey_agent model smoke --role classifier
python3 -m monkey_agent model smoke --role reasoning
python3 -m monkey_agent model smoke --role tool_builder
```

Then test the full Agent path:

```bash
python3 -m monkey_agent ask "我作为乙方软件公司的销售，明天要去拜访甲方，我应该准备什么？"
python3 -m monkey_agent ask "已完成10，总数200，完成率百分比是多少？" --context '{"numerator":10,"denominator":200}'
python3 -m monkey_agent ask "以后默认用表格输出，这是我的偏好"
python3 -m monkey_agent ask "今天上海天气怎么样？"
```

Expected behavior:

- The sales visit question should return a practical assistant-style plan, not a
  generic API/data-field clarification template.
- The percentage command should hit settled Rules first and return `5.00%`.
- The preference command should create a pending Memory candidate, which can be
  adopted after review.
- The weather command should use a capability/tool path or create a reviewed,
  generalized capability candidate instead of inventing real-time facts.
- If neither Rules, Skills, nor tools are sufficient, MonkeyAgent should ask for
  focused clarification instead of guessing.

## API

```bash
uvicorn monkey_agent.interfaces.api.app:app --host 0.0.0.0 --port 8000
```

Endpoints:

- `POST /v1/ask`
- `POST /v1/feedback`
- `POST /v1/integrations/feishu/events`
- `GET /v1/rules`
- `GET /v1/skills?type=all|yaml|agent`
- `GET /v1/agent-skills`
- `GET /v1/agent-skills/{skill_name}`
- `POST /v1/agent-skills/install`
- `POST /v1/agent-skills/import`
- `POST /v1/agent-skills/{skill_name}/enable`
- `POST /v1/agent-skills/{skill_name}/disable`
- `DELETE /v1/agent-skills/{skill_name}`
- `GET /v1/memory`
- `GET /v1/counterexamples`
- `GET /v1/capabilities`
- `GET /v1/tools`
- `GET /v1/tools/generated`
- `GET /v1/tools/generated/{tool_id}`
- `POST /v1/tools/generated/{tool_id}/enable`
- `POST /v1/tools/generated/{tool_id}/disable`
- `POST /v1/tools/generated/{tool_id}/test`
- `GET /v1/review/pending`
- `POST /v1/review/{id}/approve`
- `POST /v1/review/{id}/reject`
- `POST /v1/adopt/{id}`
- `POST /v1/goals`
- `POST /v1/goals/{goal_id}/step`
- `GET /v1/goals/{goal_id}`
- `GET /v1/goals/{goal_id}/plan`
- `GET /v1/goals/{goal_id}/events`
- `POST /v1/goals/{goal_id}/pause`
- `POST /v1/goals/{goal_id}/resume`
- `GET /v1/runs`
- `GET /v1/runs?type=ask|goal|tool`
- `GET /v1/runs/latest`
- `GET /v1/runs/{run_id}`

## Trace / Run Records

Every Ask and Goal execution writes a local trace summary into the personal
workspace. Tool Builder attempts also create a separate tool run.

```text
.monkey_agent/personal/runs/
  ask/
  goals/
  tools/
```

Trace answers why a request was routed a certain way, which Rules / Skills /
Tools / Memory / Counterexamples were involved, and whether pending review,
generated tools, errors, or human confirmation appeared.

```bash
python3 -m monkey_agent runs list
python3 -m monkey_agent runs latest --type ask
python3 -m monkey_agent runs inspect <run-id>
```

Run records intentionally store summaries only: answer previews are truncated,
full LLM prompts are not saved, and generated tool code bodies are not copied
into trace files.

## Workspace Scope

MonkeyAgent is a single-person assistant. New Rules, Skills, Memory,
Counterexamples, generated tools, Agent Skills, goals, and pending review items
are written to the current deployment's personal workspace:

```text
.monkey_agent/personal/
  rules/
  skills/
  agent_skills/
  agent_skills.yaml
  memory/
  counterexamples/
  generated_tools/
  generated_tools.yaml
  goals/
  runs/
  pending_review/
```

Execution uses personal capability first, then global fallback:

```text
personal Rules -> global Rules -> personal YAML/Agent Skills -> global YAML Skills
-> personal Generated Tools -> global/built-in Tools -> Tool Builder
```

Different people should run independent MonkeyAgent deployments or set different
`MONKEY_AGENT_RUNTIME_DIR` values. MonkeyAgent does not expose user switching
or per-user storage semantics.

## Agent Skills

MonkeyAgent supports two skill formats:

- YAML Skills: lightweight prompt/method templates stored in `personal/skills` or `data/global/skills`.
- Agent Skills: standard `SKILL.md` packages installed into `personal/agent_skills`.

Agent Skills follow the skills.sh / Agent Skills layout:

```text
my-skill/
  SKILL.md
  scripts/
  references/
  assets/
```

`SKILL.md` must start with YAML frontmatter and include `name` plus
`description`. The `name` must match the parent directory and use lowercase
letters, numbers, and hyphens.

Install examples:

```bash
python3 -m monkey_agent skills install vercel-labs/skills --skill find-skills
python3 -m monkey_agent skills install vercel-labs/skills/find-skills
python3 -m monkey_agent skills import ./my-skill
python3 -m monkey_agent skills list --type agent
python3 -m monkey_agent skills inspect find-skills
```

v1 is intentionally read-only: MonkeyAgent loads `SKILL.md` instructions and
shows bundled files, but it does not auto-execute `scripts/` or auto-grant
`allowed-tools`.

## Learning Loop

New learning is never activated directly. User corrections and additional business context are written to `.monkey_agent/personal/pending_review`. After a human approves them, they are promoted into one of four personal stores:

- Rules: deterministic formulas, APIs, SQL/tool rules, and business definitions.
- Skills: reusable task methods, prompts, and workflows.
- Memory: user preferences and stable personal defaults.
- Counterexamples: bad cases and corrections used by evaluators.

User adoption flow:

```bash
python3 -m monkey_agent ask "搜索 LangGraph 是什么"
python3 -m monkey_agent review list
python3 -m monkey_agent adopt <candidate-id>
```

`adopt` is a user-friendly alias for approving a pending candidate. For
capability-backed Rules, adoption binds the approved Rule to the original tool
through `handler: capability_tool`, so future matching questions execute from
settled Rules before any new exploration.

Conversational adoption is also supported. When MonkeyAgent creates a pending
candidate, the response includes an `adoption_prompt`, for example:

```text
是否同意将本次结果沉淀为正式 Skill？同意请回复“同意沉淀 skill_xxx”
```

If the next user message says `同意沉淀` / `采用` / `approve` / `adopt`, MonkeyAgent
approves the latest pending candidate automatically. To target a specific
candidate, pass it in context:

```bash
python3 -m monkey_agent ask "同意沉淀" --context '{"candidate_id":"skill_xxx"}'
```

MonkeyAgent avoids over-learning one-off questions. Stable executable
capabilities, such as weather or Feishu integrations, can still create a pending
Rule immediately. Public search answers and broad one-off tasks are first stored
as lightweight usage observations. Only explicit learning requests or repeated
similar questions create pending Skills and trigger an adoption prompt.

Unknown capability flow:

```text
question with no matching capability
-> explore existing callable capabilities
-> if a capability solves it, return the result and create a pending Rule candidate
-> otherwise run controlled Tool Builder for tool/API/function-like gaps
-> validate generated code, run dry-run tests, and register generated tools
-> .monkey_agent/personal/pending_review/rules, .monkey_agent/personal/pending_review/skills, or .monkey_agent/personal/pending_review/counterexamples
-> clarification questions
-> human review
-> settled capability for future calls
```

Weather queries are backed by the built-in Open-Meteo capability. Open-Meteo's
Geocoding API resolves place names, and its Forecast API returns weather data for
latitude/longitude coordinates.

Feishu/Lark message requests are backed by the Feishu IM v1 message/create
capability. If credentials or recipient details are missing, MonkeyAgent keeps
the public support evidence and creates a pending Rule with a handler draft
instead of pretending it can send the message.

Public information questions are backed by the Web Search capability. When a
search succeeds, MonkeyAgent answers from public evidence and creates a pending
Skill candidate. When a stable integration/API path is found, MonkeyAgent asks
the configured LLM to draft reviewed-only Rule code; when stability is low, it
asks the LLM to draft a Skill instead.

Tool Builder adds a controlled self-evolution path for missing API/function
capabilities. Low-risk read-only generated tools can be auto-enabled after
static safety checks and dry-run tests. Write or medium/high-risk generated
tools are registered with `confirm` permission, so they cannot perform external
side effects without explicit user confirmation.

## Feishu Bot

MonkeyAgent can be exposed as a Feishu/Lark text bot through:

```text
Feishu im.message.receive_v1
-> POST /v1/integrations/feishu/events
-> MonkeyAgent.ask(question, context={channel: feishu, feishu_sender_id: ...})
-> Feishu message/create reply to the same chat_id
```

Environment variables:

```env
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_VERIFICATION_TOKEN=xxx
FEISHU_ENCRYPT_KEY=
FEISHU_BASE_URL=https://open.feishu.cn/open-apis
FEISHU_ALLOWED_USERS=
FEISHU_ALLOWED_CHATS=
FEISHU_DEFAULT_USER_PREFIX=feishu
```

First version supports plain event callbacks with `Verification Token`.
Encrypted callbacks are detected and rejected with a clear status until the
decryptor is added. To try it:

```bash
python3 -m monkey_agent serve --port 8000
```

Expose the service with a public HTTPS URL, then configure the Feishu event
subscription request URL:

```text
https://your-domain.example/v1/integrations/feishu/events
```

Subscribe to `im.message.receive_v1`, add the bot to a chat, and ask it a
question by private message or by mentioning it in a group. Feishu sender and
chat metadata are passed through `context`; learning still writes to the single
personal workspace for this deployment.

## Goal Engine

Goal Engine is the Harness-style path for larger objectives. It is separate
from `ask` and uses the same personal Rules, Skills, Memory, generated tools,
Tool Builder, and pending review stores.

```text
goal_intake -> LLM/heuristic planner -> task DAG
-> LangGraph checkpoint -> execute ready low-risk task -> observe evidence
-> evaluator -> continue / revise_plan / interrupt / finish
-> personal learning candidates
```

The planner first asks the configured Bailian reasoning model for a structured
DAG plan. If the model is unavailable or returns invalid JSON, MonkeyAgent falls
back to a local heuristic planner. Each task records dependencies, executor,
risk, attempts, acceptance criteria, output, evidence, and result score.

Goal execution is backed by LangGraph `StateGraph` checkpoints. `goal_id` is
used as the LangGraph `thread_id`; `.monkey_agent/personal/goals/<goal_id>/` is
a readable projection for CLI/API status, events, evidence, and evaluations.
When `langgraph-checkpoint-sqlite` is installed, checkpoints are stored in
`.monkey_agent/personal/goals/checkpoints.sqlite`; otherwise MonkeyAgent falls
back to an in-memory checkpointer for local development. The memory fallback is
useful for quick tests but cannot resume after the Python process exits; use the
SQLite backend for durable local goals.

Goal status is normalized for CLI/API consumers: `next_action` is exposed as
`continue`, `waiting_human`, `completed`, `failed`, or `paused`. Internal graph
sentinels are not surfaced. If a projection file is missing, the next status,
plan, event, or step read will rebuild it from the checkpoint when possible.

Only read-only exploration, dry-run validation, and candidate generation are
automatic. External writes, real message sending, and formal promotion of
pending candidates trigger a LangGraph interrupt and require explicit
confirmation, for example `monkey goal step <goal-id> --confirm`.

Tool Builder is intentionally conservative. It runs for tool/API/integration or
automation-style goals, and for stable external query gaps such as weather. It
does not run for ordinary personal advice questions, which stay on the Ask or
Goal reasoning path. Generated Rule candidates should describe a reusable
capability, not one sample city, date, or input sentence.
