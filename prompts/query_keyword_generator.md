# 查询关键词生成器

## 任务

根据用户画像和当前技术热点，生成 3-5 个数据库搜索关键词，用于 ILIKE 模糊匹配召回候选文章。

无论用户是否提供 query，都走这一步，逻辑统一。

---

## 输入

### 用户阅读偏好
{reading_habit}

### 用户风格画像
{persona}

### 当前技术热点（最近 24h）
{trending_tags}

### 用户输入
{query}

---

## 关键词生成规则

**有 query 时**：
- 围绕 query 扩展，补充相关方向和上下游技术
- 保留 query 中的专有名词原样，不要替换或泛化
- 补充 1-2 个与 query 强相关的热点 tag（如果有交集）

**无 query 时**：
- 从用户核心关注领域中，选当前热点 tags 中权重最高的方向
- 优先选择用户画像中权重"高"的子主题与热点的交集
- 如果没有交集，直接从用户高权重子主题中选

**通用规则**：
- 结合 persona.md 中的阅读动机（偏好对比分析 → 生成 "A vs B" 类关键词）
- 结合 reading_habit.md 中的领域深度偏好（专业 → 选深度技术话题，入门 → 选概念性话题）
- 只提取专有名词：项目名、产品名、框架名、模型名、协议名、公司名
- 禁止提取泛词：AI、LLM、open source、framework、API、machine learning 等
- 关键词应来自用户画像中的中文专有名词和领域描述，中英文分别生成对应表达
- 每个关键词必须足够具体，能在数据库中精确定位到相关内容
- **中文关键词**：用中文专有名词、框架名、产品名（如"大模型推理优化"、"RAG检索策略"）
- **英文关键词**：用英文专有名词、项目名、框架名（如"vLLM inference optimization"、"RAG chunking strategies"）
- 禁止提取泛词：AI、LLM、open source、framework、API、machine learning、大模型、机器学习等

---

## 输出格式

生成两套关键词，中英文各 3-5 个，分别用于中文数据库和英文数据库的 ILIKE 模糊匹配。

中英文关键词应语义对齐（同一话题的中英文表达），关键词数量保持一致。

```
# 中文关键词
大模型推理优化
RAG检索策略
知识库问答优化

# English keywords
vLLM inference optimization
RAG chunking strategies
knowledge base Q&A
```

中英文关键词数量：各 3-5 个，不多不少。

## 搜索执行

中文关键词走中文 ILIKE 搜索，英文关键词走英文 ILIKE 搜索，两路结果合并后去重。
