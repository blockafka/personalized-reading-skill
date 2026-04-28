#!/usr/bin/env python3
"""
配置加载器

从 config.json 读取配置，支持环境变量覆盖。

优先级：环境变量 > config.json > 默认值
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional


def load_config(config_path: Optional[Path] = None) -> dict[str, Any]:
    """加载配置文件

    Args:
        config_path: 配置文件路径，默认为当前目录的 config.json

    Returns:
        配置字典
    """
    if config_path is None:
        # 默认路径：当前脚本所在目录的 config.json
        config_path = Path(__file__).parent / "config.json"

    config_path = Path(config_path).expanduser()

    # 读取配置文件
    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)
        except json.JSONDecodeError as e:
            print(f"   ⚠️  配置文件格式错误：{e}", file=sys.stderr)
            config = {}
    else:
        print(f"   ⚠️  配置文件不存在：{config_path}", file=sys.stderr)
        config = {}

    # 环境变量覆盖（向后兼容）
    llm_config = config.get("llm", {})
    llm_config["api_key"] = os.environ.get("OPENAI_API_KEY", llm_config.get("api_key"))
    llm_config["base_url"] = os.environ.get("OPENAI_BASE_URL", llm_config.get("base_url"))
    llm_config["model"] = os.environ.get("OPENAI_MODEL", llm_config.get("model", "gpt-4o-mini"))
    llm_config["timeout"] = int(os.environ.get("OPENAI_TIMEOUT", llm_config.get("timeout", 60)))
    config["llm"] = llm_config

    # 数据库配置
    if "DATABASE_URL" in os.environ:
        config["database_url"] = os.environ["DATABASE_URL"]
    elif "database" in config:
        db = config["database"]
        config["database_url"] = (
            f"postgresql://{db.get('user', 'postgres')}:{db.get('password', '')}"
            f"@{db.get('host', 'localhost')}:{db.get('port', 5432)}/{db.get('database', 'hn_production')}"
        )

    return config


def get_llm_config(config: Optional[dict] = None) -> dict[str, Any]:
    """获取 LLM 配置

    Args:
        config: 配置字典，如果为 None 则自动加载

    Returns:
        LLM 配置字典，包含 api_key, base_url, model, timeout
    """
    if config is None:
        config = load_config()
    return config.get("llm", {})


def get_database_config(config: Optional[dict] = None) -> dict[str, Any]:
    """获取数据库连接配置（关键字参数格式）

    Args:
        config: 配置字典，如果为 None 则自动加载

    Returns:
        数据库连接配置字典，包含 host, port, database, user, password 等
    """
    if config is None:
        config = load_config()

    db_config = config.get("database", {})

    # 映射字段名：config.json 用 database，psycopg2 用 dbname
    return {
        "host": db_config.get("host", "localhost"),
        "port": db_config.get("port", 5432),
        "dbname": db_config.get("database", "hn_production"),
        "user": db_config.get("user", "postgres"),
        "password": db_config.get("password", ""),
        "connect_timeout": db_config.get("connect_timeout", 10),
    }


def get_database_url(config: Optional[dict] = None) -> Optional[str]:
    """获取数据库连接 URL（向后兼容）

    Args:
        config: 配置字典，如果为 None 则自动加载

    Returns:
        数据库连接 URL，如果未配置则返回 None
    """
    if config is None:
        config = load_config()
    return config.get("database_url")


def get_behavior_config(config: Optional[dict] = None) -> dict[str, Any]:
    """获取行为追踪配置

    Args:
        config: 配置字典，如果为 None 则自动加载

    Returns:
        行为追踪配置字典
    """
    if config is None:
        config = load_config()

    defaults = {
        "strong_signal_threshold": 5,
        "decay_rate": 0.95,
        "topic_boost": 3.0,
        "min_score": 0.01,
    }

    behavior_config = config.get("behavior_tracking", {})
    return {**defaults, **behavior_config}
