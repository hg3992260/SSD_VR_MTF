"""工具层共享工具函数。"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Tuple

from .. import bridge_registry as registry
from ..bridge_client import BridgeClient
from ..context import get_ctx


def _event_handler(ctx) -> Callable[[Dict[str, Any]], None]:
    def _on_event(evt):
        if ctx.recorder is not None:
            try:
                ctx.recorder.record_event(evt.get("type"), evt.get("data") or {})
            except Exception:
                pass

    return _on_event


def get_client(auto_connect: bool = True) -> Optional[BridgeClient]:
    """返回桥客户端。

    auto_connect 时会依次尝试：
      1. 已连接的 client
      2. 显式端口（ssdvr_launch 记录的 ctx.port / SSD_VR_MCP_PORT / 默认 7799）
      3. 发现文件 + 7799-7899 顺序扫描——这样 agent 可以直接接管用户
         手工双击启动的 EXE，无需预先知道它落在哪个端口。
    """
    ctx = get_ctx()
    client = ctx.client
    if client is None:
        from .. import config
        client = BridgeClient(port=ctx.port or config.default_port())
        client.set_event_handler(_event_handler(ctx))
        ctx.client = client

    if auto_connect and not client.connected:
        client.connect(timeout=2.0)

    if auto_connect and not client.connected:
        from .. import config
        found = registry.discover_port(base=config.default_port())
        if found is not None and found != client.port:
            try:
                client.close()
            except Exception:
                pass
            new_client = BridgeClient(port=found)
            new_client.set_event_handler(_event_handler(ctx))
            if new_client.connect(timeout=3.0):
                ctx.client = new_client
                ctx.port = found
                client = new_client

    if client.connected and ctx.port != client.port:
        ctx.port = client.port
    return client


def call(op: str, args: Optional[Dict[str, Any]] = None, timeout: float = 30.0,
         tool_name: str = "") -> Tuple[bool, Any]:
    client = get_client(auto_connect=True)
    ok, data = client.call(op, args, timeout=timeout)
    ctx = get_ctx()
    if ctx.recorder is not None:
        ctx.recorder.record_tool_call(tool_name or f"bridge:{op}", args or {}, ok, data)
    if not ok:
        msg = data.get("error") if isinstance(data, dict) else str(data)
        ctx.last_error = msg
    return ok, data


def require_bridge(tool_name: str) -> Tuple[bool, Any]:
    client = get_client(auto_connect=True)
    if client is None or not client.connected:
        return False, {"error": "GUI bridge 未连接（先 ssdvr_launch，或确认 GUI 已启动且未被 --no-mcp 关闭）"}
    return True, None
