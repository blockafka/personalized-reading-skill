# Personalized Reading Skill

为 Claude Code 构建个性化文章推荐系统。通过问卷或飞书数据了解你的阅读偏好，生成画像，持续根据你的行为反馈进化推荐结果。

---

## 前置条件

1. **uv**（Python 环境管理，一次性安装）
   ```bash
   # macOS / Linux
   curl -LsSf https://astral.sh/uv/install.sh | sh
   # 或
   brew install uv
   ```
   安装后无需其他操作，后续 Python 依赖由 uv 自动管理在项目内的隔离 venv。

2. **飞书 CLI**（用于采集消息和文档）
   ```bash
   lark-cli auth login
   # 选择业务域：im（消息）+ docs（文档）
   ```

3. **数据库**：PostgreSQL，配置 `config.json`（参考 `config.example.json`）

4. **LLM API**：配置 `config.json` 中的 `api_key`、`base_url`、`model`

---

## 快速开始

### Step 1：配置

```bash
cp config.example.json config.json
# 编辑 config.json，填入你的数据库和 LLM 配置
```

### Step 2：初始化画像

在 Claude Code 中输入：

```
帮我初始化阅读画像
```

按提示回答 6 个问题（均可跳过）。可选导入飞书数据丰富画像。

### Step 3：使用

```
# 推荐文章
给我推荐文章
推荐一些 LLM 推理相关的

# 反馈行为
感兴趣 / 不感兴趣（累积 5 次后自动更新画像）

# 更新画像（新增飞书数据后）
我有新的飞书数据
```

---

## 目录结构

```
personalized_reading_skill/
├── SKILL.md                      # Skill 入口（Claude Code 运行时读取）
├── README.md                     # 本文件
├── config.example.json           # 配置模板
├── config_loader.py              # 配置加载
├── requirements.txt              # Python 依赖
├── personalized_archivist_agent.py  # 推荐引擎
├── prompts/
│   ├── intake.md                 # 问卷 prompt
│   ├── merger.md                 # 画像增量更新 prompt
│   ├── query_keyword_generator.md  # 关键词生成 prompt
│   ├── reading_habit_analyzer.md    # 阅读偏好分析
│   ├── reading_habit_builder.md     # 阅读画像生成
│   ├── persona_analyzer.md           # 风格画像分析
│   └── persona_builder.md             # 风格画像生成
├── tools/
│   ├── feishu_cli_collector.py   # 飞书数据采集
│   ├── behavior_tracker.py        # 行为信号记录
│   └── profile_writer.py          # 画像文件写入
└── users/                        # 用户画像目录（gitignore）
    └── {user_id}/
        ├── reading_habit.md
        ├── persona.md
        ├── profile.json
        ├── sync_state.json
        └── versions/              # 版本快照
```

---

## 工作原理

1. **画像初始化**：问卷 + 飞书数据 → LLM 分析 → reading_habit.md + persona.md
2. **文章推荐**：画像 + 热点 tags → LLM 生成关键词 → 数据库召回 → 画像重排 → 返回
3. **画像进化**：行为反馈（感兴趣/不感兴趣）→ tag_scores 更新 → 累积 5 次强信号 → LLM 增量更新画像

---

## License

MIT
