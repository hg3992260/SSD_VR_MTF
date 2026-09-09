"""路径 / 端口 / 解释器配置。

环境变量（可选覆盖）:
  SSD_VR_PYTHON   GUI 解释器（必须含 vtk/PySide6/SimpleITK/totalsegmentator）
  SSD_VR_REPO     仓库根目录
  SSD_VR_MCP_PORT 桥端口（默认 7799，被占时自动向后探测 7799-7899）
"""
from __future__ import annotations

import os
import sys

# 仓库根目录 = 本包上一级目录
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(PACKAGE_DIR, ".."))


def _default_python() -> str:
    """返回默认 GUI 解释器。优先使用当前解释器（MCP server 与 GUI 同环境）。"""
    if os.environ.get("SSD_VR_PYTHON"):
        return os.environ["SSD_VR_PYTHON"]
    # 已知本机 mar 环境
    candidates = [
        os.path.join("D:", os.sep, "python", "envs", "mar", "python.exe"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return sys.executable


def repo_root() -> str:
    return os.environ.get("SSD_VR_REPO") or REPO_ROOT


def viewer_script() -> str:
    return os.path.join(repo_root(), "ssd_vr_viewer.py")


def gui_python() -> str:
    return _default_python()


def default_port() -> int:
    try:
        return int(os.environ.get("SSD_VR_MCP_PORT", "7799"))
    except ValueError:
        return 7799


def record_dir() -> str:
    """事件/工具调用记录目录（SQLite + JSONL）。"""
    return os.path.join(repo_root(), "mcp_records")


def shots_dir() -> str:
    return os.path.join(record_dir(), "shots")


def gui_log_path() -> str:
    return os.path.join(record_dir(), "gui.log")


def db_path() -> str:
    return os.path.join(record_dir(), "ssd_vr.db")


def ensure_dirs() -> None:
    os.makedirs(record_dir(), exist_ok=True)
    os.makedirs(shots_dir(), exist_ok=True)
