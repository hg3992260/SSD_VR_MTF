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


# ---------------------------------------------------------------------------
# 病人 / 序列 列表：智能递归扫描
#
# 设计原则：**结果由 DICOM 标签决定，而不是由目录结构决定。**
#
#   * 递归遍历根目录（限深），收集所有"直接含 DICOM 文件"的目录
#   * 每个目录只读**少量**文件的头（首/中/尾）判断它属于哪个序列；
#     仅当同一目录里真的混了多个序列时才退化为全量读头
#   * 按 SeriesInstanceUID 合并成序列，按 (PatientID / StudyUID) 归成病人
#
# 因此下列任意一种组织方式都能正确识别，不需要用户按特定规范摆放文件：
#     root/病人/*.dcm
#     root/病人/序列/*.dcm
#     root/2024-01-15/病人/序列/*.dcm
#     root/任意嵌套/病人/序列/*.dcm
#
# 与 scan_case() 的区别：scan_case 会把**每个**文件的头都读一遍（为了精确按
# SeriesInstanceUID 分组），几百个病例时会很慢；这里每个目录读 1~3 个文件头。
# ---------------------------------------------------------------------------

_SKIP_EXT = frozenset((
    "jpg", "jpeg", "png", "bmp", "gif", "tif", "tiff", "txt", "xml", "json",
    "log", "ini", "db", "pdf", "csv", "doc", "docx", "xls", "xlsx", "py", "md",
    "nii", "nii.gz", "gz", "zip", "npy", "npz", "exe", "dll",
))

_SKIP_DIR = frozenset((
    "__macosx", ".git", ".svn", "$recycle.bin", "system volume information",
    "node_modules", "__pycache__", "recycler",
))


def _fmt_dicom_date(raw: Any) -> str:
    s = str(raw or "")
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def _read_head(path: str) -> Optional[Dict[str, str]]:
    """读一个文件的 DICOM 头（不读像素）。读不到返回 None。"""
    try:
        ds = pydicom.dcmread(path, stop_before_pixels=True, force=True)
    except Exception:
        return None
    return {
        "patient_id": str(getattr(ds, "PatientID", "") or ""),
        "patient_name": str(getattr(ds, "PatientName", "") or ""),
        "study_uid": str(getattr(ds, "StudyInstanceUID", "") or ""),
        "series_uid": str(getattr(ds, "SeriesInstanceUID", "") or ""),
        "series_desc": str(getattr(ds, "SeriesDescription", "") or ""),
        "modality": str(getattr(ds, "Modality", "") or ""),
        "study_date": _fmt_dicom_date(getattr(ds, "StudyDate", "")),
    }


def _folder_dicom_files(folder: str, max_files: int = 50000) -> List[str]:
    """目录**直接**含有的 DICOM 文件（不递归）。

    对无扩展名的文件只探测第一个候选的 DICM 魔数，避免逐个开文件；
    探测结果为否时，该目录下所有无扩展名文件都视为非 DICOM。
    """
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []

    out: List[str] = []
    magic_ok: Optional[bool] = None
    for fn in names:
        full = os.path.join(folder, fn)
        if not os.path.isfile(full):
            continue
        low = fn.lower()
        if low.endswith(".dcm"):
            out.append(full)
        else:
            ext = low.rsplit(".", 1)[-1] if "." in low else ""
            if ext in _SKIP_EXT:
                continue
            if magic_ok is None:
                magic_ok = _looks_like_dicom(full)
            if not magic_ok:
                continue
            out.append(full)
        if len(out) >= max_files:
            break
    return out


def _series_from_files(folder: str, files: List[str],
                       head: Dict[str, str]) -> Dict[str, Any]:
    total = 0
    for f in files:
        try:
            total += os.path.getsize(f)
        except OSError:
            pass
    warnings: List[str] = []
    if len(files) < 2:
        warnings.append("单层")
    if not head.get("series_uid"):
        warnings.append("无 SeriesUID")
    return {
        "folder": folder,
        "series_uid": head.get("series_uid", ""),
        "description": (head.get("series_desc")
                        or os.path.basename(os.path.normpath(folder))),
        "modality": head.get("modality", ""),
        "study_date": head.get("study_date", ""),
        "patient_id": head.get("patient_id", ""),
        "patient_name": head.get("patient_name", ""),
        "study_uid": head.get("study_uid", ""),
        "file_count": len(files),
        "size_mb": round(total / (1024 * 1024), 1),
        "warnings": warnings,
    }


def _probe_folder_series(folder: str, files: List[str]) -> List[Dict[str, Any]]:
    """把一个目录里的文件拆成序列（通常只有 1 个）。"""
    n = len(files)
    idx = sorted({0, n // 2, n - 1}) if n > 1 else [0]
    heads = [h for h in (_read_head(files[i]) for i in idx) if h]
    uids = {h.get("series_uid", "") for h in heads}

    if len(uids) <= 1:
        # 单序列（或整目录都读不到标签）→ 整目录算一个序列
        return [_series_from_files(folder, files, heads[0] if heads else {})]

    # 同一目录里混了多个序列 → 只能全量读头，按 UID 分桶
    buckets: Dict[str, Dict[str, Any]] = {}
    for f in files:
        h = _read_head(f) or {}
        key = h.get("series_uid") or f"noid::{folder}"
        b = buckets.setdefault(key, {"files": [], "head": h})
        b["files"].append(f)
        if not b["head"]:
            b["head"] = h
    return [_series_from_files(folder, b["files"], b["head"])
            for b in buckets.values()]


def _walk_dicom_folders(root: str, max_depth: int, max_folders: int):
    """递归找出所有"直接含 DICOM 文件"的目录 -> [(folder, [files]), ...]

    某目录一旦含有 DICOM 文件就当作叶子（不再往里钻），
    避免把序列目录里的备份/子目录重复计入。
    """
    found: List[Any] = []
    root_abs = os.path.abspath(root)
    for dirpath, dirnames, _fnames in os.walk(root_abs):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d.lower() not in _SKIP_DIR]
        rel = os.path.relpath(dirpath, root_abs)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if depth > max_depth:
            dirnames[:] = []
            continue
        files = _folder_dicom_files(dirpath)
        if files:
            found.append((dirpath, files))
            dirnames[:] = []            # 叶子：不再下钻
            if len(found) >= max_folders:
                break
    return found


def scan_patients(root: str, max_depth: int = 6,
                  max_folders: int = 2000) -> Dict[str, Any]:
    """智能递归扫描根目录，返回 病人 → 序列 两级列表。

    返回值::

        {"ok": True, "root": ..., "patient_count": N, "series_count": M,
         "folder_count": K,
         "patients": [
            {"key","patient_id","patient_name","display_name","study_date",
             "series_count","file_count","size_mb","modalities",
             "series": [{"folder","series_uid","description","modality",
                         "study_date","file_count","size_mb",
                         "warnings":[...],"folders":[...]}]}]}
    """
    if not root or not os.path.isdir(root):
        return {"ok": False, "error": f"目录不存在: {root}"}

    folders = _walk_dicom_folders(root, max_depth, max_folders)
    if not folders:
        return {"ok": False, "error": "该目录下没有找到 DICOM 文件", "root": root}

    series_all: List[Dict[str, Any]] = []
    for folder, files in folders:
        series_all.extend(_probe_folder_series(folder, files))

    # 同一 SeriesInstanceUID 被拆到多个目录时合并成一个序列
    merged: Dict[str, Dict[str, Any]] = {}
    for s in series_all:
        key = s["series_uid"] or f"folder::{s['folder']}"
        if key in merged:
            m = merged[key]
            m["file_count"] += s["file_count"]
            m["size_mb"] = round(m["size_mb"] + s["size_mb"], 1)
            if s["folder"] not in m["folders"]:
                m["folders"].append(s["folder"])
            m["folder_counts"][s["folder"]] = (
                m["folder_counts"].get(s["folder"], 0) + s["file_count"])
        else:
            merged[key] = dict(s, folders=[s["folder"]],
                               folder_counts={s["folder"]: s["file_count"]})

    # 一个序列被拆到多个文件夹时，加载必须挑"层数最多的那个文件夹"，
    # 否则只会加载到一部分层面 —— 静默的残缺体数据在医学影像里不能接受。
    for m in merged.values():
        fc = m["folder_counts"]
        m["load_folder"] = max(fc, key=fc.get) if fc else m["folder"]
        m["split_multi_folder"] = len(m["folders"]) > 1

    # 归成病人
    patients: Dict[str, Dict[str, Any]] = {}
    for s in merged.values():
        pkey = s["patient_id"] or s["patient_name"] or s["study_uid"] or "未知病人"
        p = patients.get(pkey)
        if p is None:
            p = patients[pkey] = {
                "key": pkey,
                "patient_id": s["patient_id"],
                "patient_name": s["patient_name"],
                "study_date": s["study_date"],
                "series": [],
                "file_count": 0,
                "size_mb": 0.0,
                "modalities": [],
            }
        p["series"].append(s)
        p["file_count"] += s["file_count"]
        p["size_mb"] = round(p["size_mb"] + s["size_mb"], 1)
        if not p["study_date"] and s["study_date"]:
            p["study_date"] = s["study_date"]
        if s["modality"] and s["modality"] not in p["modalities"]:
            p["modalities"].append(s["modality"])

    out: List[Dict[str, Any]] = []
    for p in patients.values():
        p["series"].sort(key=lambda s: (-s["file_count"], s["description"]))
        p["series_count"] = len(p["series"])
        p["display_name"] = (p["patient_name"] or p["patient_id"]
                             or os.path.basename(
                                 os.path.normpath(p["series"][0]["folder"])))
        out.append(p)
    out.sort(key=lambda p: (p["study_date"] or "", p["display_name"]))

    return {
        "ok": True,
        "root": os.path.abspath(root),
        "patient_count": len(out),
        "series_count": sum(p["series_count"] for p in out),
        "folder_count": len(folders),
        "patients": out,
    }
