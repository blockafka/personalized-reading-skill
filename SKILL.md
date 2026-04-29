---
name: personalized-reading
description: "为用户构建个性化阅读画像，通过问卷或飞书数据采集生成 reading_habit.md + persona.md，持续根据行为反馈进化，最终实现个性化文章推荐。"
argument-hint: "[user-id]"
version: "1.0.0"
user-invocable: true
allowed-tools: Read, Write, Edit, Bash
---

# 个性化阅读推荐 Skill

## 触发条件

当用户说以下任意内容时，进入**初始化模式**：
- `/personalized-reading`
- "帮我初始化阅读画像"
- "创建我的阅读偏好"
- "新建用户画像"

**初始化前必须先检查**：若 `users/{user_id}/profile.json` 已存在，说明画像已初始化过，直接告知用户已有画像，询问是查看画像还是进入推荐模式，不应再次触发问卷。

当用户说以下内容时，进入**推荐模式**：
- "给我推荐文章"
- "推荐一些 {topic} 相关的内容"

当用户说以下内容时，进入**行为反馈模式**：
- "感兴趣"、"喜欢这篇"、"不错"
- "不感兴趣"、"屏蔽这类"

当用户说以下内容时，进入**画像进化模式**：
- "我有新的飞书数据"
- "更新我的画像"

---

## 工具使用规则

| 任务 | 使用工具 |
|------|---------|
| 读取用户画像文件 | `Read` 工具 |
| 写入、更新画像文件 | `Write`、`Edit` 工具 |
| 初始化用户画像 | `Bash` → `python3 ${CLAUDE_SKILL_DIR}/tools/profile_writer.py` |
| 记录行为信号 | `Bash` → `python3 ${CLAUDE_SKILL_DIR}/tools/behavior_tracker.py` |
| 飞书 CLI 数据采集 | `Bash` → `python3 ${CLAUDE_SKILL_DIR}/tools/feishu_cli_collector.py` |
| 个性化推荐查询 | `Bash` → `python3 ${CLAUDE_SKILL_DIR}/personalized_archivist_agent.py` |

**基础目录**：用户画像写入 `./users/{user_id}/`（相对于本项目目录）。

---

## 主流程：初始化用户画像

### Step 1：问卷采集

参考 `${CLAUDE_SKILL_DIR}/prompts/intake.md` 的问题序列，依次问 6 个问题：

1. **核心关注的主题与子主题**（必填）
2. **偏好的信息类型**（新闻、深度分析、教程、案例、工具发布、讨论）
3. **偏好的内容风格与密度**（理性、犀利、技术化、高密度、轻松浏览）
4. **偏好的数据源与新鲜度**（HN、arxiv、GitHub Trending、Twitter、Reddit、突发、近期、常青）
5. **热度与领域深度偏好**（大众热点、小众深水区、入门、中级、专业）
6. **主动关注/屏蔽的关键词**

每个问题均可跳过。收集完后汇总确认，再进入下一步。

---

### Step 2：原材料导入（可选，用于丰富初始画像）

询问用户是否有飞书数据，展示两种方式：

```
是否有飞书数据用于丰富画像？（可跳过，仅凭问卷生成）

  [A] 飞书 CLI 采集（推荐）
      前置：lark-cli auth login（选择 im + docs）
      默认采集全部消息和文档
      如需限制数量，请告诉我：消息最多采集多少条？文档最多采集多少篇？

  [B] 跳过
      仅凭问卷答案生成初始画像
```

**选 A（飞书 CLI 采集）**：

前置授权（一次性）：
```bash
lark-cli auth login
# 选择业务域：im（消息）+ docs（文档）
```

执行采集（初始化和增量更新使用同一命令，脚本自动判断）：
```bash
# 默认采集全部消息和文档（推荐先用全量，如数据量过大再自行限定）
python3 ${CLAUDE_SKILL_DIR}/tools/feishu_cli_collector.py \
  --user-id {user_id} \
  --base-dir ${CLAUDE_SKILL_DIR}/users

# 如需限定采集数量，加上 --msg-limit 和 --doc-limit
python3 ${CLAUDE_SKILL_DIR}/tools/feishu_cli_collector.py \
  --user-id {user_id} \
  --base-dir ${CLAUDE_SKILL_DIR}/users \
  --msg-limit 100 \
  --doc-limit 30
```

采集完成后：
- `users/{user_id}/raw_data/messages.txt` → 新增消息记录
- `users/{user_id}/raw_data/docs.txt` → 新增文档内容
- `users/{user_id}/raw_data/batches.json` → 分批数据（供 LLM 分批处理）
- `users/{user_id}/sync_state.json` → 自动更新，记录本次采集位置

**分批处理规则**：读取 `batches.json`，若 `total_batches > 1`，则对每批分别调用 LLM（merger prompt），收集所有批次的信号后再合并写入画像。若 `total_batches == 1` 或无新数据，直接单次调用。

---

### Step 3：分析原材料

将问卷答案 + 飞书数据（如有）汇总，按两条线分析：

**线路 A（阅读偏好）**：
- 参考 `${CLAUDE_SKILL_DIR}/prompts/reading_habit_analyzer.md` 中的提取维度
- 提取：高频主题、偏好信息类型、内容风格、数据源偏好、新鲜度/热度/深度偏好、屏蔽信号

**线路 B（用户风格）**：
- 参考 `${CLAUDE_SKILL_DIR}/prompts/persona_analyzer.md` 中的提取维度
- 提取：表达风格、阅读动机、推荐理由偏好、对热门/争议内容的态度

---

### Step 4：生成并预览

参考 `${CLAUDE_SKILL_DIR}/prompts/reading_habit_builder.md` 生成 reading_habit.md 内容。
参考 `${CLAUDE_SKILL_DIR}/prompts/persona_builder.md` 生成 persona.md 内容。

向用户展示摘要，询问确认：
```
reading_habit 摘要：
  - 核心关注：{xxx}
  - 偏好来源：{xxx}
  - 内容深度：{xxx}
  - 屏蔽关键词：{xxx}

persona 摘要：
  - 阅读动机：{xxx}
  - 推荐理由格式：{xxx}
  - 对热门内容的态度：{xxx}

确认生成？还是需要调整？
```

---

### Step 5：写入文件

用户确认后，准备三个文件内容，然后调用 profile_writer.py 写入：

**1. 将生成的内容分别写入临时文件**（用 Write 工具）：
- `/tmp/reading_habit_draft.md` → reading_habit.md 内容
- `/tmp/persona_draft.md` → persona.md 内容
- `/tmp/profile_draft.json` → profile.json 内容（根据问卷答案构建）

profile.json 结构：
```json
{
  "user_id": "{user_id}",
  "tag_scores": { "{子主题}": 3.0, "{关注关键词}": 3.0 },
  "source_prefs": [0, 2, 3],
  "block_sources": [],
  "block_keywords": ["{屏蔽关键词}"],
  "content_type_prefs": ["{偏好信息类型}"],
  "freshness_pref": "recent",
  "hotness_pref": "niche",
  "depth_pref": "expert",
  "version": 1,
  "updated_at": "{ISO时间}"
}
```

source_prefs 映射：0=hacker_news, 1=twitter, 2=arxiv, 3=github_trending, 5=hugging_face, 7=reddit

**2. 调用 profile_writer.py 写入**（用 Bash）：
```bash
python3 ${CLAUDE_SKILL_DIR}/tools/profile_writer.py \
  --action create \
  --user-id {user_id} \
  --reading-habit /tmp/reading_habit_draft.md \
  --persona /tmp/persona_draft.md \
  --profile /tmp/profile_draft.json \
  --base-dir ${CLAUDE_SKILL_DIR}/users
```

告知用户：
```
✅ 阅读画像已创建！

文件位置：users/{user_id}/
  - reading_habit.md（阅读偏好）
  - persona.md（风格画像）
  - profile.json（机器可读画像，含 tag_scores）

触发推荐：给我推荐文章
记录行为：感兴趣 / 不感兴趣
```

---

## 推荐模式

用户触发推荐时：

```bash
python3 ${CLAUDE_SKILL_DIR}/personalized_archivist_agent.py \
  --user-id {user_id} \
  --query "{用户输入的 query，如无则留空}" \
  --limit 20 \
  --base-dir ${CLAUDE_SKILL_DIR}/users
```

返回结果后，按 `persona.md` 中的推荐理由格式偏好展示给用户。

---

## 行为反馈模式

用户表达"感兴趣"或"不感兴趣"时，调用 behavior_tracker.py：

```bash
python3 ${CLAUDE_SKILL_DIR}/tools/behavior_tracker.py \
  --user-id {user_id} \
  --article '{"title":"{文章标题}","tags":["{tag1}","{tag2}"]}' \
  --behavior {like|dislike} \
  --reason "{用户理由，可选}" \
  --base-dir ${CLAUDE_SKILL_DIR}/users
```

行为说明：
| 行为 | 权重 | 说明 |
|------|------|------|
| like | +2.0 | 感兴趣（强正信号） |
| dislike | -3.0 | 不感兴趣（强负信号，自动加入屏蔽词） |

- `--reason` 可选，用于记录用户感兴趣或不感兴趣的理由，帮助 LLM 理解偏好变化
- 累积 ≥5 次强信号后，自动触发 LLM 增量更新画像

---

## 画像进化模式

用户提供新飞书数据时：

1. 执行增量采集（与初始化同一命令，脚本自动读取 sync_state 只拉新数据）：
```bash
python3 ${CLAUDE_SKILL_DIR}/tools/feishu_cli_collector.py \
  --user-id {user_id} \
  --base-dir ${CLAUDE_SKILL_DIR}/users
```

2. 读取 `users/{user_id}/raw_data/batches.json`，检查 `total_batches`：
   - **= 0**：无新数据，告知用户无需更新
   - **= 1**：单批，直接进入步骤 3
   - **> 1**：多批，对每批分别执行步骤 3，收集所有批次的 patch 后统一写入

3. 用 `Read` 读取现有 `users/{user_id}/reading_habit.md` 和 `persona.md`
4. 参考 `${CLAUDE_SKILL_DIR}/prompts/merger.md` 分析当前批次内容
5. 调用 profile_writer.py 写入更新版本：
```bash
python3 ${CLAUDE_SKILL_DIR}/tools/profile_writer.py \
  --action update \
  --user-id {user_id} \
  --reading-habit-patch /tmp/reading_habit_patch.md \
  --base-dir ${CLAUDE_SKILL_DIR}/users
```

---

## 管理命令

`/list-users`：
```bash
ls ${CLAUDE_SKILL_DIR}/users/
```

查看用户画像版本：
```bash
ls ${CLAUDE_SKILL_DIR}/users/{user_id}/versions/
```

回滚到历史版本：
```bash
# 手动复制 versions/v{n}/ 下的文件到 users/{user_id}/
cp ${CLAUDE_SKILL_DIR}/users/{user_id}/versions/v{n}/reading_habit.md \
   ${CLAUDE_SKILL_DIR}/users/{user_id}/reading_habit.md
```
