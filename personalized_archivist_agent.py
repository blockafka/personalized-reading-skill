#!/usr/bin/env python3
"""
Personalized Archivist Agent: 个性化档案员

职责：
1. 加载用户画像（reading_habit.md + persona.md + profile.json）
2. 获取实时热点 tags（数据库最近 24h 高频 tags）
3. 调用 LLM 生成查询关键词
4. ILIKE 关键词召回候选集
5. 画像重排（tag_scores + source_prefs）
6. 过滤（block_keywords + block_sources）
7. 返回 top-N 个性化推荐

用法：
    python3 personalized_archivist_agent.py --user-id u_test --query "vLLM optimization"
    python3 personalized_archivist_agent.py --user-id u_test
    python3 personalized_archivist_agent.py --user-id u_test --days 30 --limit 20

配置：
    优先读取 config.json，支持环境变量覆盖（向后兼容）
    DATABASE_URL=postgresql://user:pass@host:5432/qisi
    OPENAI_API_KEY=sk-...
    OPENAI_BASE_URL=https://api.openai.com/v1  （可选）
    OPENAI_MODEL=gpt-4o-mini                   （可选）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 导入配置加载器
try:
    from config_loader import load_config, get_llm_config, get_database_config
except ImportError:
    # fallback：如果 config_loader 不存在，使用环境变量
    def load_config():
        return {}
    def get_llm_config(config=None):
        return {
            "api_key": os.environ.get("OPENAI_API_KEY"),
            "base_url": os.environ.get("OPENAI_BASE_URL"),
            "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            "timeout": 60,
        }
    def get_database_config(config=None):
        # fallback：从 DATABASE_URL 解析或返回默认配置
        db_url = os.environ.get("DATABASE_URL")
        if db_url:
            # 简单解析 postgresql://user:pass@host:port/dbname
            import re
            match = re.match(r"postgresql://([^:]+):([^@]*)@([^:]+):(\d+)/(.+)", db_url)
            if match:
                return {
                    "user": match.group(1),
                    "password": match.group(2),
                    "host": match.group(3),
                    "port": int(match.group(4)),
                    "dbname": match.group(5),
                }
        return {
            "host": "localhost",
            "port": 5432,
            "dbname": "hn_production",
            "user": "postgres",
            "password": "",
        }


# ---------------------------------------------------------------------------
# 画像加载
# ---------------------------------------------------------------------------

def load_user_profile(base_dir: Path, user_id: str) -> dict:
    """加载用户画像三件套"""
    user_dir = base_dir / user_id

    if not user_dir.exists():
        raise FileNotFoundError(f"找不到用户画像目录：{user_dir}")

    reading_habit = (user_dir / "reading_habit.md").read_text(encoding="utf-8")
    persona = (user_dir / "persona.md").read_text(encoding="utf-8")
    profile = json.loads((user_dir / "profile.json").read_text(encoding="utf-8"))

    return {
        "reading_habit": reading_habit,
        "persona": persona,
        "profile": profile,
    }


# ---------------------------------------------------------------------------
# 实时热点
# ---------------------------------------------------------------------------

def fetch_trending_tags(conn, hours: int = 24, limit: int = 20) -> list[dict]:
    """
    获取最近 N 小时数据库高频关键词（从 title 提取）

    注意：scraped_contents 表没有 tags 列，这里返回空列表
    后续可以通过 NLP 从 title 提取关键词
    """
    # TODO: 实现从 title 提取高频关键词的逻辑
    return []


# ---------------------------------------------------------------------------
# LLM 关键词生成
# ---------------------------------------------------------------------------

def _load_prompt_template() -> str:
    """加载 query_keyword_generator.md prompt 模板"""
    prompt_path = Path(__file__).parent / "prompts" / "query_keyword_generator.md"
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    # fallback：内联 prompt
    return """根据用户画像和当前技术热点，生成 3-5 个数据库搜索关键词。

## 用户阅读偏好
{reading_habit}

## 用户风格画像
{persona}

## 当前技术热点（最近 24h）
{trending_tags}

## 用户输入
{query}

直接输出关键词列表，每行一个，不要编号，不要解释。"""


def generate_keywords(
    reading_habit: str,
    persona: str,
    trending_tags: list[dict],
    query: str = "",
) -> list[str]:
    """调用 LLM 生成 3-5 个搜索关键词"""
    try:
        from openai import OpenAI
    except ImportError:
        print("   ⚠️  openai 包未安装（pip install openai），跳过 LLM 关键词生成", file=sys.stderr)
        return [query] if query else []

    llm = get_llm_config()
    api_key = llm.get("api_key")
    if not api_key:
        print("   ⚠️  未配置 LLM api_key，跳过 LLM 关键词生成", file=sys.stderr)
        return [query] if query else []

    # 禁用代理，避免系统代理干扰
    import httpx
    http_client = httpx.Client(proxy=None, timeout=llm.get("timeout", 60))

    client = OpenAI(
        api_key=api_key,
        base_url=llm.get("base_url"),
        http_client=http_client,
    )
    model = llm.get("model", "gpt-4o-mini")

    # 格式化热点 tags
    tags_text = "\n".join(
        f"{item['tag']}（{item['score']:.1f}）" for item in trending_tags
    ) or "（暂无热点数据）"

    template = _load_prompt_template()
    prompt = template.replace("{reading_habit}", reading_habit)
    prompt = prompt.replace("{persona}", persona)
    prompt = prompt.replace("{trending_tags}", tags_text)
    prompt = prompt.replace("{query}", query or "无")

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=256,
            temperature=0.3,
        )
        content = response.choices[0].message.content.strip()
        keywords = []
        for line in content.split("\n"):
            kw = line.strip().lstrip("-·•* 0123456789.")
            # 过滤 markdown 代码块标记、注释行和空内容
            if len(kw) >= 2 and not kw.startswith("`") and not kw.startswith("#"):
                keywords.append(kw)
        return keywords[:10]  # 中英文各最多 5 个，合计最多 10 个
    except Exception as e:
        print(f"   ⚠️  LLM 关键词生成失败（API 或模型配置问题）：{e}", file=sys.stderr)
        return [query] if query else []


# ---------------------------------------------------------------------------
# 数据库召回
# ---------------------------------------------------------------------------

def query_articles(
    conn,
    keywords: list[str],
    days: int = 730,
    limit: int = 100,
) -> list[dict]:
    """ILIKE 关键词召回候选文章（基于 scraped_contents 表）"""
    if not keywords:
        return []

    start_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    # 构建关键词过滤条件（同时搜索 title 和 title_en，支持中英文关键词）
    # 多词关键词拆成单词，每个单词独立 ILIKE 匹配
    keyword_clauses = []
    keyword_params = []
    for kw in keywords[:10]:
        words = [w.strip() for w in kw.split() if len(w.strip()) >= 3]
        if not words:
            words = [kw]
        for word in words[:3]:  # 每个关键词最多取前3个词
            pattern = f"%{word}%"
            keyword_clauses.append("(title ILIKE %s OR title_en ILIKE %s OR content ILIKE %s)")
            keyword_params.extend([pattern, pattern, pattern])

    if not keyword_clauses:
        return []
    keyword_where = "AND (" + " OR ".join(keyword_clauses) + ")"

    sql = f"""
        SELECT id, COALESCE(title_en, title) AS title, source_url, source, created_at
        FROM scraped_contents
        WHERE created_at >= %s
          AND (title IS NOT NULL AND title != '' OR title_en IS NOT NULL AND title_en != '')
          AND source = 0
          {keyword_where}
        ORDER BY created_at DESC
        LIMIT %s;
    """

    params = [start_date] + keyword_params + [limit]

    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        rows = cur.fetchall()
    except Exception as e:
        print(f"   ⚠️  数据库查询失败: {e}", file=sys.stderr)
        return []
    finally:
        cur.close()

    articles = []
    for row in rows:
        articles.append({
            "id": row[0],
            "title": row[1] or "",
            "url": row[2] or "",
            "source": row[3],
            "tags": [],           # scraped_contents 无 tags 列
            "created_at": row[4].isoformat() if row[4] else "",
            "confidence_score": 0.5,  # 无评分列，给默认值
        })
    return articles


# ---------------------------------------------------------------------------
# 画像重排
# ---------------------------------------------------------------------------

def calc_profile_boost(
    article: dict,
    tag_scores: dict,
    source_prefs: set,
) -> float:
    """
    计算画像加权分：
    - tag_boost：文章 title+title_en 与 tag_scores 的关键词匹配得分，归一化到 [0, 1]
    - source_boost：来源在 source_prefs 中 +0.2
    注意：scraped_contents 无 tags 列，改用标题匹配 tag_scores keys
    """
    title = article.get("title", "") or ""
    title_en = article.get("title_en", "") or ""
    combined = (title + " " + title_en).lower()

    # 用 tag_scores 的 key 做关键词匹配
    matched_score = 0.0
    for keyword, score in tag_scores.items():
        if keyword.lower() in combined:
            matched_score += score

    tag_boost = min(matched_score / 10.0, 1.0)
    source_boost = 0.2 if article.get("source") in source_prefs else 0.0
    return tag_boost + source_boost


def rerank(articles: list[dict], profile: dict) -> list[dict]:
    """按画像重排：final_score = confidence_score × (1 + profile_boost)"""
    tag_scores: dict = profile.get("tag_scores", {})
    source_prefs: set = set(profile.get("source_prefs", []))

    for article in articles:
        boost = calc_profile_boost(article, tag_scores, source_prefs)
        article["profile_boost"] = round(boost, 4)
        base = article.get("confidence_score", 0.0)
        article["final_score"] = round(base * (1 + boost), 4)

    articles.sort(key=lambda x: x["final_score"], reverse=True)
    return articles


# ---------------------------------------------------------------------------
# 过滤
# ---------------------------------------------------------------------------

def filter_articles(articles: list[dict], profile: dict) -> list[dict]:
    """过滤 block_keywords + block_sources"""
    block_keywords: list[str] = [kw.lower() for kw in profile.get("block_keywords", [])]
    block_sources: set = set(profile.get("block_sources", []))

    result = []
    for article in articles:
        # 过滤屏蔽来源
        if article.get("source") in block_sources:
            continue

        # 过滤屏蔽关键词（匹配 title）
        title_lower = article.get("title", "").lower()
        if any(kw in title_lower for kw in block_keywords):
            continue

        result.append(article)
    return result


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def execute(
    user_id: str,
    query: str = "",
    days: int = 730,
    limit: int = 20,
    base_dir: Path = None,
) -> list[dict]:
    """
    返回个性化推荐文章列表，每篇包含：
    - title, url, source, tags, created_at
    - profile_boost（画像加权分）
    - final_score（最终排序分）
    """
    if base_dir is None:
        base_dir = Path(__file__).parent / "users"

    print(f"🔍 个性化推荐：user_id={user_id}, query={query!r}")

    # 步骤 1：加载画像
    print("   📂 加载用户画像...")
    profile_data = load_user_profile(base_dir, user_id)
    reading_habit = profile_data["reading_habit"]
    persona = profile_data["persona"]
    profile = profile_data["profile"]
    print(f"      ✓ 画像版本 v{profile.get('version', 1)}，"
          f"tag_scores {len(profile.get('tag_scores', {}))} 个")

    # 步骤 2：连接数据库
    import psycopg2
    db_config = get_database_config()
    if not db_config.get("host"):
        print("   ⚠️  未配置数据库，跳过数据库查询", file=sys.stderr)
        return []

    try:
        conn = psycopg2.connect(**db_config)
    except Exception as e:
        print(f"   ⚠️  数据库连接失败: {e}", file=sys.stderr)
        return []

    try:
        # 步骤 3：获取实时热点
        print("   🔥 获取实时热点 tags...")
        trending_tags = fetch_trending_tags(conn)
        print(f"      ✓ 获取到 {len(trending_tags)} 个热点 tags")

        # 步骤 4：LLM 生成关键词
        print("   🎯 生成查询关键词...")
        keywords = generate_keywords(reading_habit, persona, trending_tags, query)
        if query and query not in keywords:
            keywords = [query] + keywords
        print(f"      ✓ 关键词：{', '.join(keywords)}")

        # 步骤 5：ILIKE 召回
        print(f"   📋 召回候选文章（最近 {days} 天）...")
        candidates = query_articles(conn, keywords, days=days, limit=limit * 5)
        print(f"      ✓ 召回 {len(candidates)} 篇候选")

        # 步骤 6：画像重排
        candidates = rerank(candidates, profile)

        # 步骤 7：过滤
        candidates = filter_articles(candidates, profile)

        # 步骤 8：取 top-N
        results = candidates[:limit]
        print(f"   ✅ 返回 {len(results)} 篇推荐")

    finally:
        conn.close()

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="个性化推荐查询")
    parser.add_argument("--user-id", required=True, help="用户 ID")
    parser.add_argument("--query", default="", help="用户查询（可为空）")
    parser.add_argument("--days", type=int, default=730, help="时间范围（天数）")
    parser.add_argument("--limit", type=int, default=20, help="返回文章数量")
    parser.add_argument("--base-dir", default="./users", help="用户画像根目录")
    args = parser.parse_args()

    results = execute(
        user_id=args.user_id,
        query=args.query,
        days=args.days,
        limit=args.limit,
        base_dir=Path(args.base_dir).expanduser(),
    )

    print("\n" + json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
