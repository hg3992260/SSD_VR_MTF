"""事件类型常量 + GuiState 快照辅助。

桥协议: TCP line-delimited JSON
  请求 {"id","op","args"}  响应 {"id","ok","data"}  事件 {"type","data","ts"}
"""
from __future__ import annotations

# GUI 主动推送的事件类型
EVENT_TYPES = [
    "load_start",
    "load_done",
    "progress",
    "error",
    "state",
    "user_action",
    "roi_start",
    "roi_done",
    "roi_error",
    "gui_ready",
    "gui_exit",
]

# 渲染模式 → 下拉框索引（与 ssd_vr_viewer.mode_combo 顺序一致）
MODE_ORDER = [
    "stable",
    "hd_surface",
    "cinematic",
    "nature_channels",
    "figure8_channels",
    "layer_channel",
    "frangi_channel",
    "bone_mono",
    "2dtf",
    "spectral",
    "exposure_render",
    "dual_volume",
]


def mode_index(mode: str) -> int:
    if mode in MODE_ORDER:
        return MODE_ORDER.index(mode)
    raise ValueError(f"未知渲染模式: {mode}（可用: {MODE_ORDER}）")


def infer_task(modality: str) -> str:
    """按 Modality 推断 TotalSegmentator 任务。"""
    m = (modality or "").upper()
    if m.startswith("MR"):
        return "total_mr"
    return "total"


def is_valid_event(etype: str) -> bool:
    return etype in EVENT_TYPES
