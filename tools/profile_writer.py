#!/usr/bin/env python3
"""
用户画像文件写入器

负责将生成的 reading_habit.md、persona.md 写入到正确的目录结构，
并生成 profile.json。支持版本快照和增量更新。

用法：
    python3 profile_writer.py --action create --user-id u_test \
        --reading-habit reading_habit.md --persona persona.md \
        --profile profile.json --base-dir ./users

    python3 profile_writer.py --action update --user-id u_test \
        --reading-habit-patch patch.md --base-dir ./users

    python3 profile_writer.py --action list --base-dir ./users
"""

from __future__ import annotations

import json
import shutil
import argparse
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional


def create_profile(
    base_dir: Path,
    user_id: str,
    reading_habit_content: str,
    persona_content: str,
    profile_data: dict,
) -> Path:
    """创建新的用户画像目录结构"""

    user_dir = base_dir / user_id
    user_dir.mkdir(parents=True, exist_ok=True)

    # 创建子目录
    (user_dir / "versions").mkdir(exist_ok=True)

    # 写入 reading_habit.md
    (user_dir / "reading_habit.md").write_text(reading_habit_content, encoding="utf-8")

    # 写入 persona.md
    (user_dir / "persona.md").write_text(persona_content, encoding="utf-8")

    # 写入 profile.json
    now = datetime.now(timezone.utc).isoformat()
    profile_data["user_id"] = user_id
    profile_data.setdefault("version", 1)
    profile_data.setdefault("created_at", now)
    profile_data["updated_at"] = now

    # 确保必需字段存在
    profile_data.setdefault("tag_scores", {})
    profile_data.setdefault("source_prefs", [])
    profile_data.setdefault("block_sources", [])
    profile_data.setdefault("block_keywords", [])
    profile_data.setdefault("content_type_prefs", [])
    profile_data.setdefault("freshness_pref", "recent")
    profile_data.setdefault("hotness_pref", "both")
    profile_data.setdefault("depth_pref", "intermediate")

    (user_dir / "profile.json").write_text(
        json.dumps(profile_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return user_dir


def update_profile(
    user_dir: Path,
    reading_habit_patch: Optional[str] = None,
    persona_patch: Optional[str] = None,
    profile_updates: Optional[dict] = None,
) -> int:
    """更新现有用户画像，先存档当前版本，再写入更新"""

    profile_path = user_dir / "profile.json"
    profile_data = json.loads(profile_path.read_text(encoding="utf-8"))

    current_version = profile_data.get("version", 1)
    new_version = current_version + 1

    # 存档当前版本
    version_dir = user_dir / "versions" / f"v{current_version}"
    version_dir.mkdir(parents=True, exist_ok=True)
    for fname in ("reading_habit.md", "persona.md", "profile.json"):
        src = user_dir / fname
        if src.exists():
            shutil.copy2(src, version_dir / fname)

    # 应用 reading_habit patch
    if reading_habit_patch:
        current_reading_habit = (user_dir / "reading_habit.md").read_text(encoding="utf-8")
        new_reading_habit = current_reading_habit + "\n\n" + reading_habit_patch
        (user_dir / "reading_habit.md").write_text(new_reading_habit, encoding="utf-8")

    # 应用 persona patch
    if persona_patch:
        current_persona = (user_dir / "persona.md").read_text(encoding="utf-8")
        new_persona = current_persona + "\n\n" + persona_patch
        (user_dir / "persona.md").write_text(new_persona, encoding="utf-8")

    # 应用 profile 更新
    if profile_updates:
        # 合并 tag_scores（不覆盖，只更新）
        if "tag_scores" in profile_updates:
            profile_data.setdefault("tag_scores", {})
            profile_data["tag_scores"].update(profile_updates["tag_scores"])

        # 其他字段直接覆盖
        for key in ["source_prefs", "block_sources", "block_keywords",
                    "content_type_prefs", "freshness_pref", "hotness_pref", "depth_pref"]:
            if key in profile_updates:
                profile_data[key] = profile_updates[key]

    # 更新版本号和时间戳
    profile_data["version"] = new_version
    profile_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    profile_path.write_text(
        json.dumps(profile_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return new_version


def list_profiles(base_dir: Path) -> list:
    """列出所有已创建的用户画像"""
    profiles = []

    if not base_dir.exists():
        return profiles

    for user_dir in sorted(base_dir.iterdir()):
        if not user_dir.is_dir():
            continue
        profile_path = user_dir / "profile.json"
        if not profile_path.exists():
            continue

        try:
            profile_data = json.loads(profile_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        profiles.append({
            "user_id": profile_data.get("user_id", user_dir.name),
            "version": profile_data.get("version", 1),
            "updated_at": profile_data.get("updated_at", ""),
            "tag_count": len(profile_data.get("tag_scores", {})),
            "source_count": len(profile_data.get("source_prefs", [])),
            "block_count": len(profile_data.get("block_keywords", [])),
        })

    return profiles


def main() -> None:
    parser = argparse.ArgumentParser(description="用户画像文件写入器")
    parser.add_argument("--action", required=True, choices=["create", "update", "list"])
    parser.add_argument("--user-id", help="用户 ID")
    parser.add_argument("--reading-habit", help="reading_habit.md 内容文件路径")
    parser.add_argument("--persona", help="persona.md 内容文件路径")
    parser.add_argument("--profile", help="profile.json 文件路径")
    parser.add_argument("--reading-habit-patch", help="reading_habit.md 增量更新内容文件路径")
    parser.add_argument("--persona-patch", help="persona.md 增量更新内容文件路径")
    parser.add_argument("--profile-updates", help="profile.json 更新内容（JSON 字符串）")
    parser.add_argument(
        "--base-dir",
        default="./users",
        help="用户画像根目录（默认：./users）",
    )

    args = parser.parse_args()
    base_dir = Path(args.base_dir).expanduser()

    if args.action == "list":
        profiles = list_profiles(base_dir)
        if not profiles:
            print("暂无已创建的用户画像")
        else:
            print(f"已创建 {len(profiles)} 个用户画像：\n")
            for p in profiles:
                updated = p["updated_at"][:10] if p["updated_at"] else "未知"
                print(f"  [{p['user_id']}]")
                print(f"    版本: v{p['version']}  更新: {updated}")
                print(f"    标签数: {p['tag_count']}  数据源: {p['source_count']}  屏蔽词: {p['block_count']}")
                print()

    elif args.action == "create":
        if not args.user_id:
            print("错误：create 操作需要 --user-id", file=sys.stderr)
            sys.exit(1)

        reading_habit_content = ""
        if args.reading_habit:
            reading_habit_content = Path(args.reading_habit).read_text(encoding="utf-8")

        persona_content = ""
        if args.persona:
            persona_content = Path(args.persona).read_text(encoding="utf-8")

        profile_data = {}
        if args.profile:
            profile_data = json.loads(Path(args.profile).read_text(encoding="utf-8"))

        user_dir = create_profile(
            base_dir, args.user_id, reading_habit_content, persona_content, profile_data
        )
        print(f"✅ 用户画像已创建：{user_dir}")

    elif args.action == "update":
        if not args.user_id:
            print("错误：update 操作需要 --user-id", file=sys.stderr)
            sys.exit(1)

        user_dir = base_dir / args.user_id
        if not user_dir.exists():
            print(f"错误：找不到用户画像目录 {user_dir}", file=sys.stderr)
            sys.exit(1)

        reading_habit_patch = None
        if args.reading_habit_patch:
            reading_habit_patch = Path(args.reading_habit_patch).read_text(encoding="utf-8")

        persona_patch = None
        if args.persona_patch:
            persona_patch = Path(args.persona_patch).read_text(encoding="utf-8")

        profile_updates = None
        if args.profile_updates:
            profile_updates = json.loads(args.profile_updates)

        new_version = update_profile(user_dir, reading_habit_patch, persona_patch, profile_updates)
        print(f"✅ 用户画像已更新到 v{new_version}：{user_dir}")


if __name__ == "__main__":
    main()
