# 阅读偏好问卷

## 开场白

```
我来帮你初始化你的个性化阅读画像。只需要回答 6 个问题，每个都可以跳过。
```

---

## 问题序列

### Q1：核心关注的主题与子主题

```
你最关注哪些主题？（可多选，也可以自定义）

主题：
  A. AI、机器学习
  B. 编程、工程
  C. 创业、商业
  D. 产品、设计
  E. 安全
  F. 科学、研究
  G. 宏观、社会
  H. 其他（请自填）

如果选了 A 或 B，可以进一步说明子主题（可跳过）：
  核心主题：AI 子主题：LLM、agents、infra、open source、RAG、推理优化……
  核心主题：编程 子主题：Rust、Python、系统编程、前端工程化、数据库……

例：A B，子主题：LLM推理、Rust async
```

- 接受字母选项或自由文本
- 主题和子主题分别存储，子主题在 `tag_scores` 中赋初始分 3.0
- 主题作为 `domains` 字段，子主题作为 `tag_scores` 的 key

---

### Q2：偏好的信息类型

```
你更喜欢哪类内容？（可多选）

  A. 新闻快讯
  B. 深度分析、观点
  C. 教程、How-to
  D. 案例研究
  E. 工具发布、项目介绍
  F. 讨论、争论
  G. 吐槽、反思
  H. 其他（请自填）

例：B D E，或者 "深度分析和工具发布"
```

- 接受字母选项或自由文本
- 写入 `reading_habit.md` 的"偏好信息类型"节
- 写入 `profile.json` 的 `content_type_prefs` 字段

---

### Q3：偏好的内容风格与密度

```
你喜欢什么风格的内容？（可多选）

风格：
  A. 理性严谨
  B. 犀利直接
  C. 技术化
  D. 叙事化
  E. 幽默
  F. 其他（请自填）

信息密度：
  G. 高密度，每段都有干货，需要认真读
  H. 轻松浏览，扫一眼就能抓住重点
  I. 其他（请自填）

例：A C F，或者 "理性技术化，高密度"
```

- 接受字母选项或自由文本
- 写入 `persona.md` 的"表达风格偏好"节

---

### Q4：偏好的数据源与新鲜度

```
你平时从哪些地方获取内容？（可多选）

来源：
  A. Hacker News
  B. Twitter、X
  C. arxiv
  D. GitHub Trending
  E. Hugging Face
  F. Reddit
  G. 其他（请自填）

新鲜度偏好（选一个）： 
  H. 突发优先，第一时间知道发生了什么
  I. 近期为主，最近一周内的内容
  J. 常青内容也行，经典好文，不在意发布时间
  K. 其他（请自填）

例：A B C H
```

- 来源数字对应 `source_prefs` 数组中的 source 枚举值
- 新鲜度写入 `profile.json` 的 `freshness_pref` 字段（"breaking"、"recent"、"evergreen"）

---

### Q5：热度与领域深度偏好

```
关于内容的热度和深度，你更偏向哪边？

热度（选一个）：
  A. 大众热点，HN 首页、Twitter 热搜，大家都在聊的
  B. 小众深水区，冷门但高质量，不在意有没有人讨论
  C. 都行，看内容质量
  D. 其他（请自填）

领域深度（选一个）： 
  E. 入门友，不需要太多背景知识
  F. 中级，有一定基础
  G. 专业深度，假设我已经很熟悉这个领域
  H. 其他（请自填）

例：B F，或者 "小众深水区，专业深度"
```

- 热度偏好写入 `profile.json` 的 `hotness_pref` 字段（"popular"、"niche"、"both"）
- 领域深度写入 `profile.json` 的 `depth_pref` 字段（"beginner"、"intermediate"、"expert"）

---

### Q6：主动关注、屏蔽的关键词

```
有没有你特别想追踪或明确不想看到的内容？（可以不填）

主动关注（技术名词、项目名）：
例：vLLM、SGLang、FlashAttention、Rust async、tokio

主动屏蔽（话题、关键词）：
例：NFT、Web3、招聘、求职、元宇宙
```

- 关注关键词写入 `reading_habit.md` 的"主动关注关键词"节，同时在 `tag_scores` 中赋初始分 3.0
- 屏蔽关键词写入 `reading_habit.md` 的"屏蔽关键词"节，同时写入 `profile.json` 的 `block_keywords`

---

## 确认汇总

收集完毕后展示：

```
信息汇总：

  📚  关注主题：{主题列表}
      子主题：{子主题列表，每个标注初始权重 3.0}
  📰  偏好信息类型：{类型列表}
  ✍️  偏好风格：{风格列表}，密度：{高密度、轻松浏览}
  🔗  偏好数据源：{来源列表}，新鲜度：{突发、近期、常青}
  🌡️  热度偏好：{大众热点、小众深水区、都行}，深度：{入门、中级、专业}
  🔍  关注关键词：{关键词列表}（若未填则省略）
  🚫  屏蔽关键词：{屏蔽列表}（若未填则省略）

确认无误？（确认、修改 [字段名]）
```

用户确认后，输出以下结构化数据供 reading_habit_builder.md 和 profile_writer.py 使用：

```json
{
  "user_id": "{user_id}",
  "domains": ["AI", "编程"],
  "tag_scores_init": {
    "LLM": 3.0, "RAG": 3.0, "Rust": 3.0, "vLLM": 3.0
  },
  "content_type_prefs": ["深度分析", "工具发布"],
  "style_prefs": ["理性严谨", "技术化"],
  "density_pref": "高密度",
  "source_prefs": [0, 2, 3],
  "freshness_pref": "recent",
  "hotness_pref": "niche",
  "depth_pref": "expert",
  "watch_keywords": ["vLLM", "SGLang"],
  "block_keywords": ["NFT", "Web3"]
}
```
