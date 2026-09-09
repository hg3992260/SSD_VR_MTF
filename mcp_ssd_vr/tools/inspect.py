"""状态与事件工具。"""
from __future__ import annotations

import json
from typing import Optional

from ..context import get_ctx
from ._util import call, get_client

TOOL_META = {"name": "ssdvr_inspect", "version": "1.0"}


def register(mcp) -> None:
    @mcp.tool()
    def ssdvr_status() -> dict:
        """健康检查：bridge_connected/port/gui_state/last_error/record_session。"""
        ctx = get_ctx()
        client = get_client(auto_connect=True)
        connected = bool(client is not None and client.connected)
        gui_state = None
        if connected:
            ok, data = call("query_state", {}, timeout=5.0, tool_name="ssdvr_status")
            if ok:
                gui_state = data
        return {
            "ok": True,
            "bridge_connected": connected,
            "port": ctx.port,
            "gui_pid": ctx.gui_pid,
            "gui_state": gui_state,
            "last_error": ctx.last_error,
            "record_session": getattr(ctx.recorder, "_jsonl_path", None) if ctx.recorder else None,
        }

    @mcp.tool()
    def ssdvr_state_snapshot() -> dict:
        """完整状态：dicom_loaded/dims/spacing/load_busy/render_window_size/render_mode/ssd_scale/vr_scale/roi_* 等。"""
        ok, data = call("query_state", {}, timeout=5.0, tool_name="ssdvr_state_snapshot")
        if not ok:
            return {"ok": False, "error": data.get("error")}
        return {"ok": True, **data}

    @mcp.tool()
    def ssdvr_wait_event(etype: str, timeout: float = 120.0, contains: Optional[str] = None) -> dict:
        """阻塞等待 GUI 推送的指定事件。etype: load_start|load_done|progress|error|state|user_action|roi_done|roi_error|gui_ready|gui_exit。contains 为事件 data 的 JSON 子串过滤。"""
        client = get_client(auto_connect=True)
        if client is None or not client.connected:
            return {"ok": False, "error": "bridge not connected"}
        evt = client.wait_event(etype, timeout=timeout, contains=contains)
        if evt is None:
            return {"ok": False, "error": f"等待 {etype} 超时 ({timeout}s)", "timed_out": True}
        return {"ok": True, "event": evt.get("type"), "data": evt.get("data"), "ts": evt.get("ts")}
