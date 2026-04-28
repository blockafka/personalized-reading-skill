#!/usr/bin/env python3
"""
飞书 CLI 数据采集器（支持增量同步）

通过 lark-cli 个人授权采集用户的飞书消息和文档，用于丰富初始画像。
支持增量同步：记录上次采集状态，下次只拉取新增数据。

前置条件：
    lark-cli auth login  # 选择 im + docs 业务域

用法：
    # 初始化（全量采集，自动写入 sync_state）
    python3 tools/feishu_cli_collector.py --user-id kafka --base-dir ./users

    # 增量更新（只拉取上次采集后的新数据）
    python3 tools/feishu_cli_collector.py --user-id kafka --base-dir ./users

    # 指定输出目录（不使用 sync_state）
    python3 tools/feishu_cli_collector.py --output ./raw_data/

输出：
    - messages.txt：个人消息记录（仅新增）
    - docs.txt：个人文档内容（仅新增）
    - sync_state.json 自动更新（存于 users/{user_id}/）
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# 增量同步状态管理
# ---------------------------------------------------------------------------

SYNC_STATE_FILE = "sync_state.json"

# 单批 LLM 调用的字符数上限（约 8000 tokens）
BATCH_CHAR_LIMIT = 24000


def load_sync_state(user_dir: Path) -> dict:
    """读取增量同步状态，不存在则返回空状态（等价于全量采集）"""
    state_path = user_dir / SYNC_STATE_FILE
    if not state_path.exists():
        return {
            "last_msg_create_time": None,
            "seen_message_ids": [],
            "last_doc_update_time": None,
            "seen_doc_tokens": [],
        }
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "last_msg_create_time": None,
            "seen_message_ids": [],
            "last_doc_update_time": None,
            "seen_doc_tokens": [],
        }


def save_sync_state(user_dir: Path, state: dict) -> None:
    """持久化增量同步状态"""
    user_dir.mkdir(parents=True, exist_ok=True)
    state_path = user_dir / SYNC_STATE_FILE
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_msg_time(time_str: str) -> Optional[datetime]:
    """解析消息时间字符串，格式：'2026-04-26 20:17'"""
    if not time_str:
        return None
    try:
        return datetime.strptime(time_str, "%Y-%m-%d %H:%M")
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# CLI Adapter Layer（隔离 lark-cli 命令细节）
# ---------------------------------------------------------------------------

class LarkCLIAdapter:
    """封装 lark-cli 命令调用，隔离 CLI 版本变化"""

    @staticmethod
    def _run_command(cmd: list[str], timeout: int = 60) -> dict:
        """执行 lark-cli 命令，返回 JSON 结果"""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.returncode != 0:
                print(f"   ⚠️  命令执行失败：{' '.join(cmd)}", file=sys.stderr)
                print(f"      stderr: {result.stderr}", file=sys.stderr)
                return {}

            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                return {"raw_output": result.stdout}

        except subprocess.TimeoutExpired:
            print(f"   ⚠️  命令超时：{' '.join(cmd)}", file=sys.stderr)
            return {}
        except Exception as e:
            print(f"   ⚠️  命令执行异常：{e}", file=sys.stderr)
            return {}

    def list_messages(self, limit: int = 0) -> list[dict]:
        """获取个人消息列表，返回原始 message 对象（含 message_id、create_time）"""
        page_size = min(50, limit) if limit else 50
        cmd = [
            "lark-cli", "im", "+messages-search",
            "--page-all",
            "--page-size", str(page_size),
            "--format", "json",
        ]
        data = self._run_command(cmd, timeout=120)
        items = data.get("data", {}).get("messages", [])
        return items[:limit] if limit else items

    def list_docs(self, limit: int = 0) -> list[dict]:
        """获取个人文档列表，返回原始 result 对象（含 token、update_time）"""
        page_size = min(limit, 20) if limit else 20
        cmd = [
            "lark-cli", "docs", "+search",
            "--query", "",
            "--page-size", str(page_size),
            "--format", "json",
        ]
        data = self._run_command(cmd)
        items = data.get("data", {}).get("results", [])
        return items[:limit] if limit else items

    def get_doc_content(self, doc_token: str) -> str:
        """获取文档内容（DOCX），返回 markdown 文本"""
        cmd = [
            "lark-cli", "docs", "+fetch",
            "--doc", doc_token,
            "--format", "json",
        ]
        data = self._run_command(cmd)
        if not data.get("ok"):
            return ""
        markdown = data.get("data", {}).get("markdown", "")
        if markdown:
            if markdown.startswith("```json"):
                lines = markdown.split("\n")
                markdown = "\n".join(lines[1:-1])
            return markdown.strip()
        return ""

    def get_sheet_content(self, sheet_token: str) -> str:
        """获取电子表格内容"""
        cmd = [
            "lark-cli", "sheets", "+read",
            "--spreadsheet-token", sheet_token,
        ]
        data = self._run_command(cmd, timeout=30)
        if not data.get("ok"):
            return ""
        value_range = data.get("data", {}).get("valueRange", {})
        rows = value_range.get("values", [])
        if not rows:
            return ""
        lines = [" | ".join(str(cell) for cell in row) for row in rows]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 消息采集（含增量过滤）
# ---------------------------------------------------------------------------

def collect_im_messages(
    limit: int = 200,
    sync_state: Optional[dict] = None,
) -> tuple[list[str], dict]:
    """
    采集个人消息，返回 (新增消息文本列表, 更新后的 sync_state 片段)

    增量逻辑：
    - 跳过 message_id 已在 seen_message_ids 中的消息
    - 跳过 create_time <= last_msg_create_time 的消息
    """
    print(f"   📱 采集个人消息（limit={limit}）...", file=sys.stderr)

    adapter = LarkCLIAdapter()
    raw_messages = adapter.list_messages(limit)

    if not raw_messages:
        print(f"      ⚠️  未获取到消息", file=sys.stderr)
        return [], {}

    print(f"      ✓ 获取到 {len(raw_messages)} 条原始消息", file=sys.stderr)

    # 增量过滤
    state = sync_state or {}
    seen_ids = set(state.get("seen_message_ids", []))
    last_time_str = state.get("last_msg_create_time")
    last_time = _parse_msg_time(last_time_str) if last_time_str else None

    new_messages = []
    new_seen_ids = list(seen_ids)
    latest_time_str = last_time_str

    for msg in raw_messages:
        msg_id = msg.get("message_id", "")
        create_time_str = msg.get("create_time", "")

        # 跳过已见过的消息
        if msg_id and msg_id in seen_ids:
            continue

        # 跳过时间早于上次同步的消息
        if last_time and create_time_str:
            msg_time = _parse_msg_time(create_time_str)
            if msg_time and msg_time <= last_time:
                continue

        # 记录新消息 ID
        if msg_id:
            new_seen_ids.append(msg_id)

        # 更新最新时间
        if create_time_str:
            if not latest_time_str:
                latest_time_str = create_time_str
            else:
                msg_time = _parse_msg_time(create_time_str)
                cur_latest = _parse_msg_time(latest_time_str)
                if msg_time and cur_latest and msg_time > cur_latest:
                    latest_time_str = create_time_str

        new_messages.append(msg)

    skipped = len(raw_messages) - len(new_messages)
    print(f"      ✓ 新增 {len(new_messages)} 条（跳过 {skipped} 条已同步）", file=sys.stderr)

    # 提取消息文本
    texts = []
    for msg in new_messages:
        msg_type = msg.get("msg_type", "")
        raw_content = msg.get("content", "")

        if not raw_content:
            continue

        content = ""
        if isinstance(raw_content, str) and raw_content.startswith("{"):
            try:
                content_obj = json.loads(raw_content)
                if msg_type == "text":
                    content = content_obj.get("text", "")
                elif msg_type == "post":
                    text_parts = []
                    for line in content_obj.get("content", []):
                        for seg in line:
                            if seg.get("tag") in ("text", "a"):
                                text_parts.append(seg.get("text", ""))
                    content = " ".join(text_parts)
                else:
                    content = content_obj.get("text", "")
            except json.JSONDecodeError:
                content = raw_content
        else:
            content = raw_content

        content = content.strip()
        if content and content not in ("[图片]", "[文件]", "[表情]", "[语音]"):
            texts.append(content)

    # 返回更新后的状态片段（只包含消息相关字段）
    state_update = {
        "last_msg_create_time": latest_time_str,
        "seen_message_ids": new_seen_ids[-2000:],  # 最多保留 2000 条 ID，防止无限增长
    }
    return texts, state_update


# ---------------------------------------------------------------------------
# 文档采集（含增量过滤）
# ---------------------------------------------------------------------------

def collect_docs(
    limit: int = 50,
    sync_state: Optional[dict] = None,
) -> tuple[list[str], dict]:
    """
    采集个人文档，返回 (新增文档文本列表, 更新后的 sync_state 片段)

    增量逻辑：
    - 跳过 token 已在 seen_doc_tokens 中的文档
    - 跳过 update_time <= last_doc_update_time 的文档
    """
    print(f"   📄 采集个人文档（limit={limit}）...", file=sys.stderr)

    adapter = LarkCLIAdapter()
    raw_docs = adapter.list_docs(limit)

    if not raw_docs:
        print(f"      ⚠️  未获取到文档", file=sys.stderr)
        return [], {}

    print(f"      ✓ 获取到 {len(raw_docs)} 篇原始文档", file=sys.stderr)

    # 增量过滤
    state = sync_state or {}
    seen_tokens = set(state.get("seen_doc_tokens", []))
    last_update_time = state.get("last_doc_update_time")  # Unix timestamp

    new_docs = []
    new_seen_tokens = list(seen_tokens)
    latest_update_time = last_update_time

    for doc in raw_docs:
        result_meta = doc.get("result_meta", {})
        token = result_meta.get("token", "")
        update_time = result_meta.get("update_time")  # Unix timestamp (int)

        # 跳过已见过的文档
        if token and token in seen_tokens:
            continue

        # 跳过更新时间早于上次同步的文档
        if last_update_time and update_time:
            if int(update_time) <= int(last_update_time):
                continue

        # 记录新文档 token
        if token:
            new_seen_tokens.append(token)

        # 更新最新时间
        if update_time:
            if not latest_update_time or int(update_time) > int(latest_update_time):
                latest_update_time = update_time

        new_docs.append(doc)

    skipped = len(raw_docs) - len(new_docs)
    print(f"      ✓ 新增 {len(new_docs)} 篇（跳过 {skipped} 篇已同步）", file=sys.stderr)

    # 拉取文档内容
    texts = []
    for doc in new_docs:
        result_meta = doc.get("result_meta", {})
        doc_id = result_meta.get("token", "")
        title = result_meta.get("title_highlighted", "") or result_meta.get("title", "")
        doc_type = result_meta.get("doc_types", "").upper()

        if not doc_id:
            continue

        print(f"      拉取文档：{title} ({doc_type})...", file=sys.stderr)

        if doc_type in ("DOCX", "DOC"):
            content = adapter.get_doc_content(doc_id)
        elif doc_type == "SHEET":
            content = adapter.get_sheet_content(doc_id)
        else:
            print(f"         ⚠️  不支持的文档类型：{doc_type}", file=sys.stderr)
            continue

        if not content or len(content.strip()) < 20:
            print(f"         内容为空，跳过", file=sys.stderr)
            continue

        doc_text = f"## 《{title}》\n\n{content.strip()}\n"
        texts.append(doc_text)

    state_update = {
        "last_doc_update_time": latest_update_time,
        "seen_doc_tokens": new_seen_tokens[-500:],  # 最多保留 500 个 token
    }
    return texts, state_update


# ---------------------------------------------------------------------------
# 分批逻辑
# ---------------------------------------------------------------------------

def split_into_batches(
    messages: list[str],
    docs: list[str],
    char_limit: int = BATCH_CHAR_LIMIT,
) -> list[dict]:
    """
    将消息和文档按字符数上限分批，每批返回：
    {
        "batch_index": 0,
        "total_batches": N,
        "messages": [...],
        "docs": [...],
        "char_count": 12345,
    }
    """
    batches = []
    current_msgs = []
    current_docs = []
    current_chars = 0

    def flush():
        if current_msgs or current_docs:
            batches.append({
                "messages": list(current_msgs),
                "docs": list(current_docs),
                "char_count": current_chars,
            })

    # 先放消息
    for msg in messages:
        msg_len = len(msg)
        if current_chars + msg_len > char_limit and (current_msgs or current_docs):
            flush()
            current_msgs.clear()
            current_docs.clear()
            current_chars = 0
        current_msgs.append(msg)
        current_chars += msg_len

    # 再放文档（文档通常更长，单独处理）
    for doc in docs:
        doc_len = len(doc)
        if current_chars + doc_len > char_limit and (current_msgs or current_docs):
            flush()
            current_msgs.clear()
            current_docs.clear()
            current_chars = 0
        current_docs.append(doc)
        current_chars += doc_len

    flush()

    # 标注批次信息
    total = len(batches)
    for i, batch in enumerate(batches):
        batch["batch_index"] = i
        batch["total_batches"] = total

    return batches


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="飞书 CLI 数据采集（支持增量同步）")
    parser.add_argument("--output", default=None, help="输出目录（不使用 sync_state 时指定）")
    parser.add_argument("--user-id", default=None, help="用户 ID（用于定位 sync_state）")
    parser.add_argument("--base-dir", default="./users", help="用户画像根目录")
    parser.add_argument("--msg-limit", type=int, default=0, help="消息数量上限（0=不限制）")
    parser.add_argument("--doc-limit", type=int, default=0, help="文档数量上限（0=不限制）")
    parser.add_argument("--batch-char-limit", type=int, default=BATCH_CHAR_LIMIT,
                        help=f"单批 LLM 字符数上限（默认 {BATCH_CHAR_LIMIT}）")
    args = parser.parse_args()

    # 确定输出目录和 sync_state 路径
    use_sync = bool(args.user_id)
    if use_sync:
        user_dir = Path(args.base_dir).expanduser() / args.user_id
        output_dir = user_dir / "raw_data"
        sync_state = load_sync_state(user_dir)
        is_incremental = bool(
            sync_state.get("last_msg_create_time") or sync_state.get("last_doc_update_time")
        )
        mode = "增量更新" if is_incremental else "全量采集（首次）"
    else:
        output_dir = Path(args.output or "./raw_data/").expanduser()
        sync_state = None
        is_incremental = False
        mode = "全量采集（无 sync_state）"

    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"🔍 飞书 CLI 数据采集 [{mode}]")
    print(f"   输出目录：{output_dir}")

    # 采集消息
    messages, msg_state = collect_im_messages(args.msg_limit, sync_state)

    # 采集文档
    docs, doc_state = collect_docs(args.doc_limit, sync_state)

    # 分批
    batches = split_into_batches(messages, docs, args.batch_char_limit)

    # 写入文件
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    messages_file = output_dir / "messages.txt"
    if messages:
        messages_file.write_text(
            f"# 飞书消息记录（CLI 采集）\n"
            f"采集时间：{now_str}\n"
            f"共 {len(messages)} 条新增消息\n\n"
            f"---\n\n" +
            "\n\n".join(messages),
            encoding="utf-8",
        )
        print(f"   ✅ 消息已保存到 {messages_file}")
    else:
        messages_file.write_text(
            f"# 飞书消息记录（CLI 采集）\n"
            f"采集时间：{now_str}\n"
            f"无新增消息\n",
            encoding="utf-8",
        )
        print(f"   ℹ️  无新增消息")

    docs_file = output_dir / "docs.txt"
    if docs:
        docs_file.write_text(
            f"# 飞书文档内容（CLI 采集）\n"
            f"采集时间：{now_str}\n"
            f"共 {len(docs)} 篇新增文档\n\n"
            f"---\n\n" +
            "\n\n".join(docs),
            encoding="utf-8",
        )
        print(f"   ✅ 文档已保存到 {docs_file}")
    else:
        docs_file.write_text(
            f"# 飞书文档内容（CLI 采集）\n"
            f"采集时间：{now_str}\n"
            f"无新增文档\n",
            encoding="utf-8",
        )
        print(f"   ℹ️  无新增文档")

    # 输出分批信息
    if batches:
        print(f"\n   📦 数据分批：共 {len(batches)} 批")
        for b in batches:
            print(f"      批次 {b['batch_index'] + 1}/{b['total_batches']}："
                  f" {len(b['messages'])} 条消息 + {len(b['docs'])} 篇文档"
                  f"（{b['char_count']} 字符）")
    else:
        print(f"\n   ℹ️  无新增数据，无需 LLM 处理")

    # 更新 sync_state
    if use_sync:
        new_state = {**sync_state, **msg_state, **doc_state}
        new_state["last_collected_at"] = now_str
        save_sync_state(user_dir, new_state)
        print(f"\n   💾 sync_state 已更新：{user_dir / SYNC_STATE_FILE}")

    print(f"\n✅ 采集完成")

    # 将分批结果输出到 stdout（供调用方读取）
    if batches:
        batches_file = output_dir / "batches.json"
        batches_file.write_text(
            json.dumps(batches, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"   📄 分批数据已写入 {batches_file}")


if __name__ == "__main__":
    main()
