#!/usr/bin/env python3
"""
行为信号记录与 tag_scores 更新

职责：
1. 记录用户行为（click/read_complete/like/save/skip/dislike）
2. 更新 profile.json 中的 tag_scores
3. 累积 ≥5 次强信号后触发 LLM 增量更新 reading_habit.md

用法：
    python3 tools/behavior_tracker.py --user-id u_test \
        --article '{"title":"vLLM v0.4","tags":["LLM","inference"]}' \
        --behavior save

    python3 tools/behavior_tracker.py --user-id u_test \
        --article '{"title":"NFT marketplace","tags":["NFT","Web3"]}' \
        --behavior dislike
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# 导入配置加载器
sys.path.insert(0, str(Path(__file__).parent.parent))
try:
    from config_loader import get_llm_config
except ImportError:
    # fallback：如果 config_loader 不存在，使用环境变量
    def get_llm_config(config=None):
        return {
            "api_key": os.environ.get("OPENAI_API_KEY"),
            "base_url": os.environ.get("OPENAI_BASE_URL"),
            "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            "timeout": 60,
        }

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DECAY_RATE  = 0.95
TOPIC_BOOST = 3.0
MIN_SCORE   = 0.01

# 行为权重
BEHAVIOR_WEIGHTS: dict[str, float] = {
    "like":    2.0,  # 感兴趣（强正信号）
    "dislike": -3.0, # 不感兴趣（强负信号，写入 block_keywords）
}

# 强信号行为（累积触发 LLM 更新）
STRONG_SIGNAL_BEHAVIORS = {"like", "dislike"}

# 触发 LLM 更新的强信号阈值
STRONG_SIGNAL_THRESHOLD = 5

# 强信号队列文件名
SIGNAL_QUEUE_FILE = "signal_queue.json"


# ---------------------------------------------------------------------------
# tag_scores 更新
# ---------------------------------------------------------------------------

def update_tag_scores(
    current: dict[str, float],
    triggered_tags: list[str],
    weight: float = 1.0,
) -> dict[str, float]:
    """
    衰减所有 tag，对触发的 tags 做 boost。
    weight > 0 → boost；weight < 0 → decay 加速（直接减分）
    """
    updated = {k: v * DECAY_RATE for k, v in current.items()}

    if weight > 0:
        for tag in triggered_tags:
            updated[tag] = updated.get(tag, 0.0) + TOPIC_BOOST * weight
    else:
        # 负信号：加速衰减（再乘一次 DECAY_RATE，并减去绝对值 boost）
        for tag in triggered_tags:
            current_val = updated.get(tag, 0.0)
            updated[tag] = max(current_val * DECAY_RATE + TOPIC_BOOST * weight, 0.0)

    return {k: v for k, v in updated.items() if v >= MIN_SCORE}


# ---------------------------------------------------------------------------
# 强信号队列
# ---------------------------------------------------------------------------

def _load_signal_queue(user_dir: Path) -> list[dict]:
    queue_path = user_dir / SIGNAL_QUEUE_FILE
    if not queue_path.exists():
        return []
    try:
        return json.loads(queue_path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_signal_queue(user_dir: Path, queue: list[dict]) -> None:
    queue_path = user_dir / SIGNAL_QUEUE_FILE
    queue_path.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_signal(user_dir: Path, article: dict, behavior: str, reason: str = None) -> list[dict]:
    """追加一条强信号记录，返回当前队列"""
    queue = _load_signal_queue(user_dir)
    record = {
        "title": article.get("title", ""),
        "tags": article.get("tags", []),
        "behavior": behavior,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if reason:
        record["reason"] = reason
    queue.append(record)
    _save_signal_queue(user_dir, queue)
    return queue


def _clear_signal_queue(user_dir: Path) -> None:
    _save_signal_queue(user_dir, [])


# ---------------------------------------------------------------------------
# LLM 增量更新
# ---------------------------------------------------------------------------

def _trigger_llm_update(user_dir: Path, signal_queue: list[dict]) -> bool:
    """
    调用 LLM（merger.md prompt）增量更新 reading_habit.md + persona.md。
    更新成功后通过 profile_writer.py 写入新版本。
    返回是否成功。
    """
    try:
        from openai import OpenAI
    except ImportError:
        print("   ⚠️  未安装 openai，跳过 LLM 增量更新", file=sys.stderr)
        return False

    llm = get_llm_config()
    api_key = llm.get("api_key")
    if not api_key:
        print("   ⚠️  未配置 api_key，跳过 LLM 增量更新", file=sys.stderr)
        return False

    # 加载 merger.md prompt 模板
    merger_prompt_path = Path(__file__).parent.parent / "prompts" / "merger.md"
    if not merger_prompt_path.exists():
        print("   ⚠️  找不到 prompts/merger.md，跳过 LLM 增量更新", file=sys.stderr)
        return False

    merger_template = merger_prompt_path.read_text(encoding="utf-8")

    # 加载当前画像
    reading_habit = (user_dir / "reading_habit.md").read_text(encoding="utf-8")
    persona = (user_dir / "persona.md").read_text(encoding="utf-8")

    # 格式化强信号记录
    signals_text = "\n".join(
        f"- [{s['behavior']}] {s['title']} | tags: {', '.join(s['tags'])}"
        + (f" | reason: {s.get('reason', '')}" if s.get('reason') else "")
        for s in signal_queue
    )

    prompt = f"""{merger_template}

---

## 当前 reading_habit.md

{reading_habit}

---

## 当前 persona.md

{persona}

---

## 最近强信号行为记录

{signals_text}
"""

    # 禁用代理，避免系统代理干扰
    import httpx
    http_client = httpx.Client(proxy=None, timeout=llm.get("timeout", 60))

    client = OpenAI(
        api_key=api_key,
        base_url=llm.get("base_url"),
        http_client=http_client,
    )
    model = llm.get("model", "gpt-4o-mini")

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4096,
            temperature=0.3,
        )
        llm_output = response.choices[0].message.content.strip()
    except Exception as e:
        print(f"   ⚠️  LLM 调用失败: {e}", file=sys.stderr)
        return False

    # 解析 LLM 输出，提取 reading_habit patch 和 persona patch
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    reading_habit_patch = _extract_section(llm_output, "reading_habit.md 更新")
    persona_patch = _extract_section(llm_output, "persona.md 更新")

    # 替换 patch 中的 {日期} 占位符
    if reading_habit_patch:
        reading_habit_patch = reading_habit_patch.replace("{日期}", today)
    if persona_patch:
        persona_patch = persona_patch.replace("{日期}", today)

    if not reading_habit_patch and not persona_patch:
        print("   ℹ️  LLM 判断无需更新画像")
        return True

    # 调用 profile_writer.py 写入更新
    sys.path.insert(0, str(Path(__file__).parent))
    from profile_writer import update_profile

    new_version = update_profile(
        user_dir,
        reading_habit_patch=reading_habit_patch or None,
        persona_patch=persona_patch or None,
    )
    print(f"   ✅ 画像已增量更新到 v{new_version}")
    return True


def _extract_section(text: str, section_marker: str) -> str:
    """从 LLM 输出中提取指定节的内容"""
    marker = f"=== {section_marker} ==="
    if marker not in text:
        return ""
    start = text.index(marker) + len(marker)
    # 找下一个 === 或文末
    next_marker = text.find("===", start)
    end = next_marker if next_marker != -1 else len(text)
    content = text[start:end].strip()
    # 过滤掉"无更新"占位
    if "无更新" in content or not content:
        return ""
    return content


# ---------------------------------------------------------------------------
# 主接口
# ---------------------------------------------------------------------------

def record_behavior(
    user_id: str,
    article: dict,
    behavior: str,
    reason: str = None,
    base_dir: Path = None,
) -> None:
    """
    记录用户行为，更新 tag_scores。

    Args:
        user_id: 用户 ID
        article: 文章信息，需包含 title 和 tags
        behavior: like | dislike
        reason: 用户理由（可选）
    """
    if behavior not in BEHAVIOR_WEIGHTS:
        raise ValueError(f"未知行为类型：{behavior}，支持：{list(BEHAVIOR_WEIGHTS)}")

    if base_dir is None:
        base_dir = Path(__file__).parent.parent / "users"

    user_dir = base_dir / user_id
    if not user_dir.exists():
        raise FileNotFoundError(f"找不到用户画像目录：{user_dir}")

    profile_path = user_dir / "profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))

    tags = article.get("tags", [])
    weight = BEHAVIOR_WEIGHTS[behavior]

    # 更新 tag_scores
    profile["tag_scores"] = update_tag_scores(profile.get("tag_scores", {}), tags, weight)

    # dislike → 写入 block_keywords
    if behavior == "dislike":
        block_keywords: list = profile.setdefault("block_keywords", [])
        for tag in tags:
            if tag not in block_keywords:
                block_keywords.append(tag)
        print(f"   🚫 已将 {tags} 加入屏蔽关键词")

    profile["updated_at"] = datetime.now(timezone.utc).isoformat()
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"   ✓ tag_scores 已更新（行为：{behavior}，tags：{tags}）")

    # 强信号：写入队列，检查是否触发 LLM 更新
    if behavior in STRONG_SIGNAL_BEHAVIORS:
        queue = _append_signal(user_dir, article, behavior, reason)
        print(f"   📌 强信号队列：{len(queue)}/{STRONG_SIGNAL_THRESHOLD}")

        if len(queue) >= STRONG_SIGNAL_THRESHOLD:
            print(f"   🔄 累积 {len(queue)} 条强信号，触发 LLM 增量更新...")
            success = _trigger_llm_update(user_dir, queue)
            if success:
                _clear_signal_queue(user_dir)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="行为信号记录与 tag_scores 更新")
    parser.add_argument("--user-id", required=True, help="用户 ID")
    parser.add_argument("--article", required=True, help="文章信息（JSON 字符串）")
    parser.add_argument(
        "--behavior", required=True,
        choices=["like", "dislike"],
        help="行为类型",
    )
    parser.add_argument("--reason", default=None, help="用户理由（可选）")
    parser.add_argument("--base-dir", default="./users", help="用户画像根目录")
    args = parser.parse_args()

    article = json.loads(args.article)
    base_dir = Path(args.base_dir).expanduser()

    record_behavior(args.user_id, article, args.behavior, args.reason, base_dir)

    # 打印更新后的 tag_scores
    profile_path = base_dir / args.user_id / "profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    top_tags = sorted(profile["tag_scores"].items(), key=lambda x: x[1], reverse=True)[:5]
    print(f"\n当前 top tag_scores：{dict(top_tags)}")


if __name__ == "__main__":
    main()
