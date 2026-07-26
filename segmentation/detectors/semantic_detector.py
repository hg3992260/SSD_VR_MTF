from __future__ import annotations

import os
import tempfile
from typing import Dict, Optional

import numpy as np
import SimpleITK as sitk

from ..roi_label_map import TOTALSEG_TOTAL


def detect_semantic(
    sitk_image: sitk.Image,
    spacing_original: tuple,
    progress_cb=None,
    task: str = "total",
) -> np.ndarray:

    min_sp = min(spacing_original)
    need_resample = min_sp < 0.8
    target_sp = (1.5, 1.5, 1.5)

    # #region debug-point A:semantic-input
    import json, urllib.request, time
    _p = '.dbg/roi-result-drift.env'
    _u, _s = 'http://127.0.0.1:7777/event', 'roi-result-drift'
    try:
        with open(_p, encoding='utf-8') as f:
            _c = f.read()
        _u = next((l.split('=', 1)[1].strip() for l in _c.split('\n') if l.startswith('DEBUG_SERVER_URL=')), _u)
        _s = next((l.split('=', 1)[1].strip() for l in _c.split('\n') if l.startswith('DEBUG_SESSION_ID=')), _s)
    except Exception:
        pass
    _payload = {
        'sessionId': _s,
        'runId': 'pre-fix',
        'hypothesisId': 'A',
        'location': 'semantic_detector.py:detect_semantic',
        'msg': '[DEBUG] semantic input geometry',
        'data': {
            'spacing_original': tuple(float(v) for v in spacing_original),
            'sitk_size': tuple(int(v) for v in sitk_image.GetSize()),
            'sitk_spacing': tuple(float(v) for v in sitk_image.GetSpacing()),
            'sitk_origin': tuple(float(v) for v in sitk_image.GetOrigin()),
            'sitk_direction': tuple(float(v) for v in sitk_image.GetDirection()),
            'need_resample': bool(need_resample),
            'target_sp': tuple(float(v) for v in target_sp),
        },
        'ts': int(time.time() * 1000),
    }
    try:
        urllib.request.urlopen(
            urllib.request.Request(
                _u,
                data=json.dumps(_payload).encode(),
                headers={'Content-Type': 'application/json'},
            ),
            timeout=0.8,
        ).read()
    except Exception:
        pass
    # #endregion

    if need_resample:
        if progress_cb:
            progress_cb(5, f"下采样到1.5mm各向同性 (原始{min_sp:.3f}mm)...")
        resampled = _resample(sitk_image, target_sp)
    else:
        resampled = sitk_image

    if progress_cb:
        progress_cb(10, "TotalSegmentator 推理中 (GPU, 约2-5分钟)...")

    tmpdir = tempfile.mkdtemp(prefix="totalseg_")
    nii_path = os.path.join(tmpdir, "input.nii.gz")
    sitk.WriteImage(resampled, nii_path)

    from totalsegmentator.python_api import totalsegmentator
    seg_nifti = totalsegmentator(nii_path, task=task, fast=True, device="gpu", quiet=True, output_type="nifti")

    out_nii = os.path.join(tmpdir, "seg.nii.gz")
    import nibabel as nib
    nib.save(seg_nifti, out_nii)
    seg_lowres_img = sitk.ReadImage(out_nii)

    if need_resample:
        if progress_cb:
            progress_cb(75, f"语义分割上采样回原始分辨率 ({min_sp:.3f}mm)...")
        seg_hi = _upsample(seg_lowres_img, sitk_image)
    else:
        seg_hi = seg_lowres_img

    label_map = sitk.GetArrayFromImage(seg_hi).astype(np.int16)

    # #region debug-point D:semantic-output
    import json, urllib.request, time
    _p = '.dbg/roi-result-drift.env'
    _u, _s = 'http://127.0.0.1:7777/event', 'roi-result-drift'
    try:
        with open(_p, encoding='utf-8') as f:
            _c = f.read()
        _u = next((l.split('=', 1)[1].strip() for l in _c.split('\n') if l.startswith('DEBUG_SERVER_URL=')), _u)
        _s = next((l.split('=', 1)[1].strip() for l in _c.split('\n') if l.startswith('DEBUG_SESSION_ID=')), _s)
    except Exception:
        pass
    _nz = label_map[label_map > 0]
    _ids, _cnts = (np.unique(_nz, return_counts=True) if _nz.size else (np.array([], dtype=np.int32), np.array([], dtype=np.int64)))
    _top = [
        {
            'label_id': int(i),
            'name': TOTALSEG_TOTAL.get(int(i), (f'u{int(i)}', '?'))[0],
            'count': int(c),
        }
        for i, c in sorted(zip(_ids.tolist(), _cnts.tolist()), key=lambda t: t[1], reverse=True)[:10]
    ]
    _payload = {
        'sessionId': _s,
        'runId': 'pre-fix',
        'hypothesisId': 'D',
        'location': 'semantic_detector.py:detect_semantic',
        'msg': '[DEBUG] semantic label_map summary',
        'data': {
            'label_map_shape': tuple(int(v) for v in label_map.shape),
            'nonzero_voxels': int(_nz.size),
            'unique_labels': int(len(_ids)),
            'top_labels': _top,
        },
        'ts': int(time.time() * 1000),
    }
    try:
        urllib.request.urlopen(
            urllib.request.Request(
                _u,
                data=json.dumps(_payload).encode(),
                headers={'Content-Type': 'application/json'},
            ),
            timeout=0.8,
        ).read()
    except Exception:
        pass
    # #endregion

    if progress_cb:
        n_labels = len(np.unique(label_map)) - 1
        progress_cb(85, f"语义分割完成: {n_labels}/{len(TOTALSEG_TOTAL)} 类标签有效")

    try:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception:
        pass

    return label_map


def _resample(image: sitk.Image, target_spacing: tuple) -> sitk.Image:
    size = image.GetSize()
    spacing = image.GetSpacing()
    new_size = [int(size[i] * spacing[i] / target_spacing[i]) for i in range(3)]
    resampler = sitk.ResampleImageFilter()
    resampler.SetSize(new_size)
    resampler.SetOutputSpacing(target_spacing)
    resampler.SetOutputOrigin(image.GetOrigin())
    resampler.SetOutputDirection(image.GetDirection())
    resampler.SetInterpolator(sitk.sitkLinear)
    return resampler.Execute(image)


def _upsample(seg_lowres: sitk.Image, reference: sitk.Image) -> sitk.Image:
    resampler = sitk.ResampleImageFilter()
    resampler.SetSize(reference.GetSize())
    resampler.SetOutputSpacing(reference.GetSpacing())
    resampler.SetOutputOrigin(reference.GetOrigin())
    resampler.SetOutputDirection(reference.GetDirection())
    resampler.SetInterpolator(sitk.sitkNearestNeighbor)
    return resampler.Execute(seg_lowres)
