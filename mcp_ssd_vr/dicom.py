"""病例结构前置分析：只读 DICOM 头（不读像素），按 SeriesInstanceUID 分组。"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import pydicom


def _nsort_key(fname: str):
    digits = "".join(ch for ch in os.path.basename(fname) if ch.isdigit())
    try:
        return int(digits) if digits else 0
    except ValueError:
        return 0


def _collect_dcm_files(path: str, max_depth: int, max_files: int) -> List[str]:
    files: List[str] = []
    for root, dirs, fnames in os.walk(path):
        depth = root[len(path):].count(os.sep)
        if depth > max_depth:
            dirs[:] = []
            continue
        for fn in sorted(fnames):
            if len(files) >= max_files:
                return files
            full = os.path.join(root, fn)
            if fn.lower().endswith(".dcm") or (not fn.lower().split(".")[-1].startswith(("jpg", "png", "txt", "xml", "json", "log", "ini", "db")) and _looks_like_dicom(full)):
                files.append(full)
    return files


def _looks_like_dicom(full: str) -> bool:
    # 无扩展名的 DICOM 文件：读前 4 字节魔数 DICM（偏移 128）
    try:
        with open(full, "rb") as f:
            f.seek(128)
            magic = f.read(4)
        return magic == b"DICM"
    except OSError:
        return False


def scan_case(path: str, max_depth: int = 4, max_files: int = 50000) -> Dict[str, Any]:
    """扫描病例目录，返回按 SeriesInstanceUID 分组的序列列表。"""
    if not os.path.exists(path):
        return {"ok": False, "error": f"path not found: {path}"}

    files = _collect_dcm_files(path, max_depth, max_files)
    if not files:
        return {"ok": False, "error": "no DICOM files found", "path": path}

    series: Dict[str, Dict[str, Any]] = {}
    for full in files:
        try:
            ds = pydicom.dcmread(full, stop_before_pixels=True, force=True)
        except Exception:
            continue
        sid = getattr(ds, "SeriesInstanceUID", None) or "unknown"
        s = series.setdefault(sid, {
            "folder": os.path.dirname(full),
            "files": [],
            "series_description": str(getattr(ds, "SeriesDescription", "") or ""),
            "modality": str(getattr(ds, "Modality", "") or ""),
            "rows": int(getattr(ds, "Rows", 0) or 0),
            "cols": int(getattr(ds, "Columns", 0) or 0),
            "positions": [],
            "spacing_xy": None,
            "spacing_z": None,
        })
        s["files"].append(full)
        try:
            pos = float(ds.ImagePositionPatient[2])
            s["positions"].append(pos)
        except Exception:
            pass
        if s["spacing_xy"] is None:
            try:
                s["spacing_xy"] = [float(ds.PixelSpacing[0]), float(ds.PixelSpacing[1])]
            except Exception:
                pass

    out_series: List[Dict[str, Any]] = []
    for sid, s in series.items():
        files_n = sorted(s["files"], key=_nsort_key)
        n = len(files_n)
        positions = sorted(s["positions"])
        spacing_z = None
        if len(positions) >= 2:
            diffs = [round(b - a, 4) for a, b in zip(positions[:-1], positions[1:])]
            diffs = [d for d in diffs if d > 0]
            if diffs:
                spacing_z = round(sum(diffs) / len(diffs), 4)
        est_gb = 0.0
        if s["rows"] and s["cols"] and n:
            est_gb = round(s["rows"] * s["cols"] * n * 2 / (1024 ** 3), 3)
        warnings = []
        if n < 2:
            warnings.append("single slice")
        if spacing_z is not None and spacing_z <= 0:
            warnings.append("z spacing <= 0")
        out_series.append({
            "folder": s["folder"],
            "file_count": n,
            "series_uid": sid,
            "series_description": s["series_description"],
            "modality": s["modality"],
            "rows": s["rows"],
            "cols": s["cols"],
            "slices": n,
            "spacing_xy": s["spacing_xy"],
            "spacing_z": spacing_z,
            "instance_range": [files_n[0], files_n[-1]] if n else [],
            "est_raw_gb": est_gb,
            "warnings": warnings,
        })

    out_series.sort(key=lambda x: x["file_count"], reverse=True)
    recommended = 0
    if out_series:
        # 若有多序列且文件数相同，优先选描述含 VEN/CT/胸 等主序列；否则取文件数最多
        recommended = max(range(len(out_series)), key=lambda i: out_series[i]["file_count"])

    multi = len(out_series) > 1
    return {
        "ok": True,
        "path": path,
        "total_files": len(files),
        "series_count": len(out_series),
        "multi_series": multi,
        "recommended_index": recommended,
        "series": out_series,
        "warning": "多序列病例：建议用 series 下标或返回的 folder 逐序列加载" if multi else None,
    }


def resolve_series_path(path: str, series: Optional[int] = None) -> Dict[str, Any]:
    """把病例根目录解析为单一序列文件夹（供 load_dicom 使用）。"""
    if os.path.isfile(path):
        return {"ok": True, "path": path, "kind": "file"}
    if os.path.isdir(path):
        # 先看目录内是否本身就是单一序列（含 .dcm 文件）
        direct = [f for f in os.listdir(path) if f.lower().endswith(".dcm")]
        if direct:
            return {"ok": True, "path": path, "kind": "series_dir"}
        info = scan_case(path)
        if not info.get("ok"):
            return info
        series_list = info["series"]
        if not series_list:
            return {"ok": False, "error": "no series found"}
        idx = series if series is not None else info["recommended_index"]
        if idx < 0 or idx >= len(series_list):
            return {"ok": False, "error": f"series index out of range: {idx}"}
        chosen = series_list[idx]
        return {"ok": True, "path": chosen["folder"], "kind": "series_folder",
                "series_index": idx, "modality": chosen["modality"],
                "file_count": chosen["file_count"]}
    return {"ok": False, "error": f"invalid path: {path}"}
