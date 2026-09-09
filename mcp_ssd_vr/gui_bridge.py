"""运行在 GUI 进程内：TCP server + 主线程调度。

把 MCP server 发来的 op 请求投递到 Qt 主线程执行（QueuedConnection），
并把 GUI 主动事件（load_start/load_done/progress/roi_done/error/...）推回客户端。

协议: TCP line-delimited JSON（见 bridge_client.py）。
"""
from __future__ import annotations

import base64
import io
import json
import socket
import threading
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

from PySide6 import QtCore, QtWidgets


# ---------------------------------------------------------------------------
# 状态采集 / 截图（在主线程内执行，直接访问 ViewerWindow）
# ---------------------------------------------------------------------------

def _roi_results_count(win) -> int:
    results = getattr(win, "roi_results", None)
    if not results:
        return 0
    n = 0
    for r in results:
        n += len(getattr(r, "bones", []) or [])
        n += len(getattr(r, "vessels", []) or [])
        n += len(getattr(r, "tissues", []) or [])
    return n


def collect_state(win) -> Dict[str, Any]:
    image_data = getattr(win, "image_data", None)
    loaded = image_data is not None
    dims = None
    spacing = None
    if loaded:
        try:
            dims = list(int(v) for v in image_data.GetDimensions())
        except Exception:
            dims = None
        try:
            spacing = list(float(v) for v in image_data.GetSpacing())
        except Exception:
            spacing = None

    rw = getattr(win, "render_window", None)
    rw_size = None
    if rw is not None:
        try:
            rw_size = list(int(v) for v in rw.GetSize())
        except Exception:
            rw_size = None

    roi_pipeline = getattr(win, "roi_pipeline", None)
    roi_running = bool(roi_pipeline is not None and roi_pipeline.isRunning())

    def slider_val(name: str, default: float = 0.0) -> float:
        obj = getattr(win, name, None)
        try:
            return float(obj.slider().value()) / 100.0
        except Exception:
            return default

    def raw_val(name: str, default: int = 0) -> int:
        obj = getattr(win, name, None)
        try:
            return int(obj.slider().value())
        except Exception:
            return default

    return {
        "dicom_loaded": loaded,
        "dicom_path": _path_text(win),
        "dims": dims,
        "spacing": spacing,
        "load_busy": bool(getattr(win, "load_busy", False)),
        "render_window_size": rw_size,
        "render_mode": getattr(win, "render_mode", "stable"),
        "ssd_scale": slider_val("ssd_slider"),
        "vr_scale": slider_val("vr_slider"),
        "wl_offset": raw_val("wl_slider"),
        "ww_scale": raw_val("ww_slider", 100) / 100.0,
        "roi_task": getattr(win, "roi_current_task", "total"),
        "roi_running": roi_running,
        "roi_results_count": _roi_results_count(win),
        "last_error": getattr(win, "last_error", None),
    }


def _path_text(win) -> str:
    pe = getattr(win, "path_edit", None)
    if pe is None:
        return ""
    try:
        le = pe.line_edit()
        return le.text().strip()
    except Exception:
        return ""


def take_screenshot(win, out_dir: Optional[str] = None) -> Dict[str, Any]:
    import numpy as np
    from PIL import Image
    from vtkmodules.util import numpy_support as vtk_np

    rw = getattr(win, "render_window", None)
    if rw is None:
        return {"ok": False, "error": "no render window"}
    rw.Render()
    w2i = _import_window2image()
    w2i.SetInput(rw)
    w2i.SetInputBufferTypeToRGBA()
    w2i.ReadFrontBufferOff()
    w2i.Update()
    vtk_img = w2i.GetOutput()
    w, h, _ = vtk_img.GetDimensions()
    scalars = vtk_img.GetPointData().GetScalars()
    arr = vtk_np.vtk_to_numpy(scalars)
    arr = arr.reshape((h, w, -1))
    rgba = arr[..., :4] if arr.shape[-1] >= 4 else np.dstack([arr, np.full(arr.shape[:2], 255, np.uint8)])
    rgba = np.flipud(rgba)

    img = Image.fromarray(rgba, mode="RGBA").convert("RGB")
    out_dir = out_dir or ""
    if out_dir:
        import os
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"shot_{int(time.time()*1000)}.png")
    else:
        path = ""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()
    if path:
        with open(path, "wb") as f:
            f.write(png_bytes)

    rgb = np.asarray(img)
    mean = float(rgb.mean())
    bright = float((rgb.max(axis=2) > 50).mean() * 100.0)
    uniq = len(np.unique(rgb.reshape(-1, 3), axis=0))

    return {
        "ok": True,
        "path": path,
        "bytes": len(png_bytes),
        "png_base64": base64.b64encode(png_bytes).decode("ascii"),
        "stats": {"mean": round(mean, 2), "bright_pct": round(bright, 2), "unique_colors": int(uniq)},
    }


def _import_window2image():
    from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter
    return vtkWindowToImageFilter()


# ---------------------------------------------------------------------------
# 跨线程调度器（主线程执行 op）
# ---------------------------------------------------------------------------

class _Dispatcher(QtCore.QObject):
    _cmd = QtCore.Signal(object)

    def __init__(self, win, bridge) -> None:
        super().__init__()
        self.win = win
        self.bridge = bridge
        self._pending: Dict[str, Dict[str, Any]] = {}
        self._plock = threading.Lock()
        self._cmd.connect(self._on_cmd, QtCore.Qt.ConnectionType.QueuedConnection)

    def submit(self, req_id: str, op: str, args: Dict[str, Any], timeout: float) -> Tuple[bool, Any]:
        evt = threading.Event()
        holder: Dict[str, Any] = {}
        with self._plock:
            self._pending[req_id] = {"evt": evt, "holder": holder}
        self._cmd.emit((req_id, op, args))
        if not evt.wait(timeout):
            with self._plock:
                self._pending.pop(req_id, None)
            return False, {"error": f"op '{op}' 主线程执行超时 ({timeout}s)"}
        return holder.get("ok", False), holder.get("data", {})

    @QtCore.Slot(object)
    def _on_cmd(self, payload) -> None:
        req_id, op, args = payload
        ok = False
        data: Any = {}
        try:
            data = self._execute(op, args)
            ok = True
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            data = {"error": f"{type(e).__name__}: {e}"}
            ok = False
            try:
                self.win.last_error = data["error"]
                self.bridge.push_event("error", {"error": data["error"], "op": op})
            except Exception:
                pass
        with self._plock:
            item = self._pending.pop(req_id, None)
        if item is not None:
            item["holder"]["ok"] = ok
            item["holder"]["data"] = data
            item["evt"].set()

    # ---- op 实现 ----
    def _execute(self, op: str, args: Dict[str, Any]) -> Any:
        win = self.win
        if op == "query_state":
            return collect_state(win)
        if op == "screenshot":
            return take_screenshot(win, out_dir=args.get("out_dir"))
        if op == "load_dicom":
            return self._load_dicom(args)
        if op == "set_mode":
            return self._set_mode(args)
        if op == "set_opacity":
            return self._set_opacity(args)
        if op == "set_camera":
            return self._set_camera(args)
        if op == "set_window_level":
            return self._set_window_level(args)
        if op == "set_ssd_threshold":
            return self._set_threshold("ssd", args)
        if op == "set_vr_threshold":
            return self._set_threshold("vr", args)
        if op == "get_thresholds":
            return self._get_thresholds()
        if op == "set_cr_params":
            return self._set_cr_params(args)
        if op == "set_preprocess":
            return self._set_preprocess(args)
        if op == "set_crop":
            return self._set_crop(args)
        if op == "toggle_background":
            win.toggle_background()
            return {"bg_is_white": bool(getattr(win, "bg_is_white", False))}
        if op == "trigger_roi":
            return self._trigger_roi(args)
        if op == "list_roi_blocks":
            return self._list_roi_blocks()
        if op == "render_roi_label":
            return self._render_roi_label(args)
        if op == "render_roi_labels":
            return self._render_roi_labels(args)
        if op == "set_custom_roi":
            return self._set_custom_roi(args)
        if op == "roi_cancel":
            win.on_roi_cancel()
            return {"ok": True}
        if op == "roi_clear":
            win.on_roi_clear()
            return {"ok": True}
        if op == "set_roi_weight_path":
            return self._set_roi_weight_path(args)
        if op == "list_presets":
            return self._list_presets()
        if op == "apply_preset":
            return self._apply_preset(args)
        if op == "get_render_params":
            return self._get_render_params()
        if op == "shutdown":
            return self._shutdown()
        raise ValueError(f"unknown op: {op}")

    # ---- 具体实现 ----
    def _load_dicom(self, args: Dict[str, Any]) -> Dict[str, Any]:
        win = self.win
        if getattr(win, "load_busy", False):
            win.last_error = "load in progress"
            self.bridge.push_event("error", {"error": "load in progress: busy"})
            return {"ok": False, "error": "load in progress", "load_busy": True}
        path = args.get("path") or ""
        if not path:
            return {"ok": False, "error": "no path"}
        pe = getattr(win, "path_edit", None)
        if pe is not None:
            try:
                pe.line_edit().setText(path)
            except Exception:
                pass
        # 异步触发加载，避免阻塞主线程/桥
        QtCore.QTimer.singleShot(0, win.load_dicom)
        return {"ok": True, "accepted": True, "path": path}

    def _set_mode(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from . import state
        mode = args.get("mode") or "stable"
        win = self.win
        try:
            idx = state.mode_index(mode)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        combo = getattr(win, "mode_combo", None)
        try:
            if combo is not None:
                combo.combo_box().setCurrentIndex(idx)
        except Exception:
            pass
        win.on_mode_change(idx)
        return {"ok": True, "mode": getattr(win, "render_mode", mode), "requested": mode}

    def _set_opacity(self, args: Dict[str, Any]) -> Dict[str, Any]:
        win = self.win
        if args.get("ssd") is not None:
            self._set_slider(win, "ssd_slider", float(args["ssd"]))
        if args.get("vr") is not None:
            self._set_slider(win, "vr_slider", float(args["vr"]))
        win.on_slider_change(0)
        return {"ok": True, "ssd_scale": self._slider_scale(win, "ssd_slider"),
                "vr_scale": self._slider_scale(win, "vr_slider")}

    def _set_camera(self, args: Dict[str, Any]) -> Dict[str, Any]:
        win = self.win
        renderer = getattr(win, "renderer", None)
        if renderer is None:
            return {"ok": False, "error": "no renderer"}
        cam = renderer.GetActiveCamera()
        if args.get("reset"):
            renderer.ResetCamera()
        view = args.get("view")
        if view:
            self._apply_view(renderer, cam, view)
        az = float(args.get("azimuth", 0.0))
        el = float(args.get("elevation", 0.0))
        roll = float(args.get("roll", 0.0))
        if az:
            cam.Azimuth(az)
        if el:
            cam.Elevation(el)
        if roll:
            cam.Roll(roll)
        dolly = float(args.get("dolly", 1.0))
        if dolly != 1.0:
            cam.Dolly(dolly)
        pos = args.get("position")
        focal = args.get("focal")
        up = args.get("view_up")
        if pos and len(pos) == 3:
            cam.SetPosition(*[float(v) for v in pos])
        if focal and len(focal) == 3:
            cam.SetFocalPoint(*[float(v) for v in focal])
        if up and len(up) == 3:
            cam.SetViewUp(*[float(v) for v in up])
        va = args.get("view_angle")
        if va is not None:
            cam.SetViewAngle(float(va))
        renderer.ResetCameraClippingRange()
        if getattr(win, "render_window", None) is not None:
            win.render_window.Render()
        return self._camera_state(cam)

    def _apply_view(self, renderer, cam, view: str) -> None:
        renderer.ResetCamera()
        fp = cam.GetFocalPoint()
        pos = cam.GetPosition()
        import math
        d = math.sqrt(sum((pos[i] - fp[i]) ** 2 for i in range(3))) or 1.0
        views = {
            "coronal": ((0, -d, 0), (0, 0, 1)),
            "coronal_rear": ((0, d, 0), (0, 0, 1)),
            "sagittal": ((d, 0, 0), (0, 0, 1)),
            "sagittal_rear": ((-d, 0, 0), (0, 0, 1)),
            "axial": ((0, 0, d), (0, 1, 0)),
            "axial_rear": ((0, 0, -d), (0, 1, 0)),
            "three_quarter": ((d * 0.7, -d * 0.7, d * 0.7), (0, 0, 1)),
            "front_top": ((0, -d * 0.6, d * 0.8), (0, 0, 1)),
        }
        if view in views:
            off, up = views[view]
            cam.SetPosition(fp[0] + off[0], fp[1] + off[1], fp[2] + off[2])
            cam.SetViewUp(*up)

    def _set_window_level(self, args: Dict[str, Any]) -> Dict[str, Any]:
        win = self.win
        if args.get("wl") is not None:
            self._set_slider(win, "wl_slider", float(args["wl"]))
        if args.get("ww") is not None:
            self._set_slider(win, "ww_slider", float(args["ww"]) * 100.0)
        win.on_ww_wl_change()
        return {"ok": True, "wl_offset": self._raw_val(win, "wl_slider"),
                "ww_scale": self._raw_val(win, "ww_slider", 100) / 100.0}

    def _set_threshold(self, which: str, args: Dict[str, Any]) -> Dict[str, Any]:
        win = self.win
        lower = args.get("lower")
        upper = args.get("upper")
        if lower is None or upper is None:
            return {"ok": False, "error": "need lower+upper"}
        slider = getattr(win, f"{which}_threshold_slider", None)
        if slider is None:
            return {"ok": False, "error": f"no {which} threshold slider"}
        try:
            slider.setValues(int(lower), int(upper))
        except Exception:
            try:
                slider.setValues(float(lower), float(upper))
            except Exception:
                return {"ok": False, "error": "setValues failed"}
        if which == "ssd":
            win.on_ssd_threshold_change(int(lower), int(upper))
        else:
            win.on_vr_threshold_change(int(lower), int(upper))
        return {"ok": True, "lower": int(lower), "upper": int(upper)}

    def _get_thresholds(self) -> Dict[str, Any]:
        win = self.win
        out = {}
        for which in ("ssd", "vr"):
            slider = getattr(win, f"{which}_threshold_slider", None)
            if slider is None:
                out[which] = None
                continue
            try:
                l, u = slider.value()
                out[which] = [int(l), int(u)]
            except Exception:
                try:
                    out[which] = [int(slider._lower), int(slider._upper)]
                except Exception:
                    out[which] = None
        return out

    def _set_cr_params(self, args: Dict[str, Any]) -> Dict[str, Any]:
        win = self.win
        for key in ("mc_quality", "scatter_blend", "scatter_g", "er_exposure", "cr_denoise",
                    "step_factor_primary", "step_factor_shadow"):
            if key in args and hasattr(win, key):
                setattr(win, key, float(args[key]))
        win._apply_cr_runtime_params()
        return {"ok": True}

    def _set_preprocess(self, args: Dict[str, Any]) -> Dict[str, Any]:
        win = self.win
        mapping = {
            "denoise": "denoise_method",
            "use_clahe": "use_clahe",
            "use_frangi": "use_frangi",
            "use_distance_field": "use_distance_field",
            "use_2d_tf": "use_2d_tf",
            "use_2d_tf_bone": "use_2d_tf_bone",
            "cpu_render": "cpu_render",
            "vram_threshold_gb": "vram_threshold_gb",
        }
        for k, attr in mapping.items():
            if k in args:
                setattr(win, attr, args[k])
        return {"ok": True}

    def _set_crop(self, args: Dict[str, Any]) -> Dict[str, Any]:
        win = self.win
        enabled = bool(args.get("enabled", True))
        chk = getattr(win, "check_crop", None)
        if chk is not None:
            chk.setChecked(enabled)
        bw = getattr(win, "box_widget", None)
        if bw is not None:
            if enabled:
                bw.On()
            else:
                bw.Off()
        return {"ok": True, "crop": enabled}

    def _trigger_roi(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from . import state
        win = self.win
        if getattr(win, "image_data", None) is None:
            return {"ok": False, "error": "no dicom loaded"}
        task = args.get("task")
        if task in (None, "", "auto"):
            modality = self._detect_modality(win)
            task = state.infer_task(modality)
        win.roi_current_task = task
        # 同步 GUI 的分割任务下拉框（程序更新后新增 roi_task_combo）
        if hasattr(win, "_set_roi_task_combo"):
            try:
                win._set_roi_task_combo(task)
            except Exception:
                pass
        QtCore.QTimer.singleShot(0, win.on_roi_start)
        return {"ok": True, "task": task, "fast": bool(args.get("fast", True))}

    def _detect_modality(self, win) -> str:
        try:
            img = getattr(win, "original_sitk_image", None)
            if img is not None:
                for key in ("0008|0060",):
                    if img.HasMetaDataKey(key):
                        return img.GetMetaData(key)
                for key in img.GetMetaDataKeys():
                    if key.endswith("0008|0060"):
                        return img.GetMetaData(key)
        except Exception:
            pass
        return "CT"

    def _list_roi_blocks(self) -> Dict[str, Any]:
        win = self.win
        results = getattr(win, "roi_results", None)
        blocks = []
        if results:
            for r in results:
                for cat in ("bones", "vessels", "tissues"):
                    for b in getattr(r, cat, []) or []:
                        blocks.append({
                            "label_id": int(getattr(b, "label_id", 0)),
                            "name": getattr(b, "anatomical_name", "") or getattr(b, "category", ""),
                            "category": getattr(b, "category", cat),
                            "volume_cm3": round(float(getattr(b, "volume_cm3", 0.0)), 3),
                            "voxel_count": int(getattr(b, "voxel_count", 0)),
                            "region": getattr(b, "region", r.region),
                            "bbox_z": list(getattr(b, "bbox_z", (0, 0))),
                            "bbox_y": list(getattr(b, "bbox_y", (0, 0))),
                            "bbox_x": list(getattr(b, "bbox_x", (0, 0))),
                        })
        blocks.sort(key=lambda x: x["volume_cm3"], reverse=True)
        return {"ok": True, "count": len(blocks), "blocks": blocks}

    def _render_roi_label(self, args: Dict[str, Any]) -> Dict[str, Any]:
        win = self.win
        label_id = args.get("label_id")
        if label_id in (None, 0):
            win._restore_vr_pixels()
            if getattr(win, "render_window", None) is not None:
                win.render_window.Render()
            return {"ok": True, "label_id": 0, "action": "restore"}
        results = getattr(win, "roi_results", None)
        target = None
        if results:
            for r in results:
                for cat in ("bones", "vessels", "tissues"):
                    for b in getattr(r, cat, []) or []:
                        if int(getattr(b, "label_id", -1)) == int(label_id):
                            target = b
                            break
        if target is None:
            return {"ok": False, "error": f"label_id {label_id} not found"}
        win._apply_roi_pixel_replacement([target])
        if getattr(win, "render_window", None) is not None:
            win.render_window.Render()
        return {"ok": True, "label_id": int(label_id), "action": "render"}

    def _set_custom_roi(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """注入自定义 ROI 掩膜（如 ASPECTS 梗死区）并高亮渲染。
        args: {
          mask_b64: base64 的 uint8 掩膜（与原始图像同 shape 或 bbox 内 shape）,
          bbox: {"z":[z0,z1],"y":[y0,y1],"x":[x0,x1]},   # 掩膜在原图中的 bbox
          label_id, name, color_hu
        }
        """
        import base64 as _b64
        import numpy as _np
        win = self.win
        mask_b64 = args.get("mask_b64")
        mask_path = args.get("mask_path")
        bbox = args.get("bbox") or {}
        if not mask_b64 and not mask_path:
            return {"ok": False, "error": "mask_b64 or mask_path required"}
        if mask_path:
            try:
                arr = _np.load(mask_path).astype(_np.uint8)
            except Exception as e:
                return {"ok": False, "error": f"bad npy: {e}"}
        else:
            try:
                arr = _np.frombuffer(_b64.b64decode(mask_b64), dtype=_np.uint8)
            except Exception as e:
                return {"ok": False, "error": f"bad base64: {e}"}
        # 尝试恢复 shape：优先 bbox，其次原始图像
        orig = getattr(win, "original_sitk_image", None) or getattr(win, "image_data", None)
        z, y, x = None, None, None
        if bbox:
            z = bbox.get("z"); y = bbox.get("y"); x = bbox.get("x")
        if z and y and x:
            want = (z[1]-z[0]) * (y[1]-y[0]) * (x[1]-x[0])
        elif orig is not None:
            dims = orig.GetDimensions()
            z, y, x = [0, dims[2]], [0, dims[1]], [0, dims[0]]
            want = dims[2]*dims[1]*dims[0]
        else:
            return {"ok": False, "error": "no bbox nor image dims"}
        if arr.size != want:
            return {"ok": False, "error": f"mask size {arr.size} != bbox size {want}"}
        mask = arr.reshape(z[1]-z[0], y[1]-y[0], x[1]-x[0]).astype(bool)
        from segmentation.roi_types import ROIBlock
        from segmentation.roi_types import ROIRegionResult
        label_id = int(args.get("label_id") or 99001)
        name = args.get("name") or "梗死区"
        block = ROIBlock(
            region="全局",
            category="tissues",
            mask=mask,
            bbox_z=(int(z[0]), int(z[1])),
            bbox_y=(int(y[0]), int(y[1])),
            bbox_x=(int(x[0]), int(x[1])),
            z_range_mm=(0.0, 0.0),
            volume_cm3=float(mask.sum()),
            voxel_count=int(mask.sum()),
            label_id=label_id,
            anatomical_name=name,
        )
        # 注入 roi_results
        results = getattr(win, "roi_results", None)
        if not results:
            rr = ROIRegionResult(region="全局")
            results = [rr]
            win.roi_results = results
        results[0].tissues.append(block)
        win._apply_roi_pixel_replacement([block])
        if getattr(win, "render_window", None) is not None:
            win.render_window.Render()
        return {"ok": True, "label_id": label_id, "name": name, "voxels": int(mask.sum())}

    def _render_roi_labels(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """同时叠加高亮多个结构的 mask（如全部盆腔组织）。args: {label_ids: [..]}"""
        win = self.win
        label_ids = args.get("label_ids") or []
        if not label_ids:
            win._restore_vr_pixels()
            if getattr(win, "render_window", None) is not None:
                win.render_window.Render()
            return {"ok": True, "label_ids": [], "action": "restore"}
        results = getattr(win, "roi_results", None)
        blocks = []
        found = set()
        if results:
            for r in results:
                for cat in ("bones", "vessels", "tissues"):
                    for b in getattr(r, cat, []) or []:
                        lid = int(getattr(b, "label_id", -1))
                        if lid in set(int(x) for x in label_ids):
                            blocks.append(b)
                            found.add(lid)
        if not blocks:
            return {"ok": False, "error": f"no blocks for label_ids {label_ids}"}
        win._apply_roi_pixel_replacement(blocks)
        if getattr(win, "render_window", None) is not None:
            win.render_window.Render()
        return {"ok": True, "label_ids": sorted(found), "count": len(blocks), "action": "render"}

    def _set_roi_weight_path(self, args: Dict[str, Any]) -> Dict[str, Any]:
        win = self.win
        path = args.get("path") or ""
        if not path:
            tasks = win._scan_weight_dir(getattr(win, "roi_weight_edit").text().strip()) \
                if getattr(win, "roi_weight_edit", None) else []
            return {"ok": True, "tasks": [t[1] for t in tasks],
                    "current_task": getattr(win, "roi_current_task", "total")}
        import os
        if not os.path.isdir(path):
            return {"ok": False, "error": f"path not found: {path}"}
        tasks = win._scan_weight_dir(path)
        if getattr(win, "roi_weight_edit", None) is not None:
            win.roi_weight_edit.setText(path)
        if tasks:
            win.roi_current_task = tasks[0][1]
            os.environ["nnUNet_results"] = path
        return {"ok": True, "tasks": [t[1] for t in tasks],
                "current_task": getattr(win, "roi_current_task", "total")}

    def _list_presets(self) -> Dict[str, Any]:
        win = self.win
        presets = list(getattr(win, "slicer_presets", {}).keys())
        return {"ok": True, "count": len(presets), "presets": presets}

    def _apply_preset(self, args: Dict[str, Any]) -> Dict[str, Any]:
        win = self.win
        name = args.get("name")
        presets = getattr(win, "slicer_presets", {})
        if not name or name not in presets:
            return {"ok": False, "error": f"unknown preset: {name}"}
        p = presets[name]
        if p.get("opacity"):
            win.vr_opacity_points = list(p["opacity"])
        if p.get("color"):
            win.vr_color_points = list(p["color"])
        vol = getattr(win, "current_vr_volume", None)
        if vol is not None:
            prop = vol.GetProperty()
            if p.get("ambient") is not None:
                prop.SetAmbient(p["ambient"])
            if p.get("diffuse") is not None:
                prop.SetDiffuse(p["diffuse"])
            if p.get("specular") is not None:
                prop.SetSpecular(p["specular"])
            if p.get("specularPower") is not None:
                prop.SetSpecularPower(p["specularPower"])
            win._update_vr_transfer_functions()
        if getattr(win, "render_window", None) is not None:
            win.render_window.Render()
        return {"ok": True, "preset": name}

    def _get_render_params(self) -> Dict[str, Any]:
        win = self.win
        return {
            "render_mode": getattr(win, "render_mode", "stable"),
            "ssd_scale": self._slider_scale(win, "ssd_slider"),
            "vr_scale": self._slider_scale(win, "vr_slider"),
            "wl_offset": self._raw_val(win, "wl_slider"),
            "ww_scale": self._raw_val(win, "ww_slider", 100) / 100.0,
            "ssd_opacity_points": getattr(win, "ssd_opacity_points", None),
            "vr_opacity_points": getattr(win, "vr_opacity_points", None),
            "denoise_method": getattr(win, "denoise_method", "gaussian"),
            "cpu_render": getattr(win, "cpu_render", False),
            "vram_threshold_gb": getattr(win, "vram_threshold_gb", 10),
        }

    def _shutdown(self) -> Dict[str, Any]:
        QtCore.QTimer.singleShot(0, self._do_shutdown)
        return {"ok": True, "shutting_down": True}

    def _do_shutdown(self) -> None:
        win = self.win
        try:
            win.close()
        except Exception:
            pass
        QtWidgets.QApplication.quit()

    # ---- 小工具 ----
    @staticmethod
    def _set_slider(win, name: str, val: float) -> None:
        obj = getattr(win, name, None)
        if obj is None:
            return
        slider = obj.slider()
        slider.setValue(int(round(val)))

    @staticmethod
    def _slider_scale(win, name: str) -> float:
        obj = getattr(win, name, None)
        try:
            return float(obj.slider().value()) / 100.0
        except Exception:
            return 0.0

    @staticmethod
    def _raw_val(win, name: str, default: int = 0) -> int:
        obj = getattr(win, name, None)
        try:
            return int(obj.slider().value())
        except Exception:
            return default

    @staticmethod
    def _camera_state(cam) -> Dict[str, Any]:
        pos = cam.GetPosition()
        fp = cam.GetFocalPoint()
        up = cam.GetViewUp()
        import math
        d = math.sqrt(sum((pos[i] - fp[i]) ** 2 for i in range(3)))
        return {
            "position": [round(float(v), 3) for v in pos],
            "focal": [round(float(v), 3) for v in fp],
            "view_up": [round(float(v), 3) for v in up],
            "distance": round(d, 3),
            "view_angle": round(float(cam.GetViewAngle()), 3),
        }


# ---------------------------------------------------------------------------
# TCP server
# ---------------------------------------------------------------------------

class GuiBridgeServer:
    def __init__(self, win, port: int = 7799, host: str = "127.0.0.1") -> None:
        self.win = win
        self.port = port
        self.host = host
        self.dispatcher = _Dispatcher(win, self)
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._clients: List[socket.socket] = []
        self._clients_lock = threading.Lock()
        self._closing = threading.Event()

    def start(self) -> None:
        self._running.set()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        self.push_event("gui_ready", {"port": self.port})

    def _serve(self) -> None:
        while self._running.is_set():
            try:
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self._sock.bind((self.host, self.port))
                self._sock.listen(1)
                self._sock.settimeout(1.0)
            except OSError:
                self.port += 1
                continue
            while self._running.is_set():
                try:
                    conn, _ = self._sock.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                with self._clients_lock:
                    self._clients.append(conn)
                threading.Thread(target=self._client_loop, args=(conn,), daemon=True).start()
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def _client_loop(self, conn: socket.socket) -> None:
        buf = b""
        while self._running.is_set() and not self._closing.is_set():
            try:
                chunk = conn.recv(65536)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line.decode("utf-8"))
                except Exception:
                    continue
                if "id" in msg and "op" in msg:
                    self._handle_request(conn, msg)
        with self._clients_lock:
            if conn in self._clients:
                self._clients.remove(conn)
        try:
            conn.close()
        except OSError:
            pass

    def _handle_request(self, conn: socket.socket, msg: Dict[str, Any]) -> None:
        req_id = msg["id"]
        op = msg.get("op", "")
        args = msg.get("args", {}) or {}
        timeout = float(msg.get("timeout", 120.0))
        ok, data = self.dispatcher.submit(req_id, op, args, timeout)
        resp = {"id": req_id, "ok": ok, "data": data}
        self._send(conn, resp)

    def _send(self, conn: socket.socket, obj: Dict[str, Any]) -> None:
        try:
            conn.sendall((json.dumps(obj, ensure_ascii=False, default=str) + "\n").encode("utf-8"))
        except OSError:
            pass

    def push_event(self, etype: str, data: Dict[str, Any]) -> None:
        evt = {"type": etype, "data": data, "ts": time.time()}
        with self._clients_lock:
            clients = list(self._clients)
        for c in clients:
            self._send(c, evt)

    def stop(self) -> None:
        self._closing.set()
        self._running.clear()
        with self._clients_lock:
            for c in self._clients:
                try:
                    c.close()
                except OSError:
                    pass
            self._clients.clear()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass


def start_bridge(win, port: int) -> GuiBridgeServer:
    bridge = GuiBridgeServer(win, port=port)
    win._mcp_bridge = bridge
    bridge.start()
    return bridge
