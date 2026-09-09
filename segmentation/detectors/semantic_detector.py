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
    # brain_structures 用官方 0.5mm 模型, 由 TS 内部处理重采样, 不预降采样到 1.5mm
    hi_res_task = task == "brain_structures"
    need_resample = (not hi_res_task) and min_sp < 0.8
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

    _apply_nnunet_serial_patches()
    from totalsegmentator.python_api import totalsegmentator
    import nnunetv2.training.nnUNetTrainer.variants.training_length.nnUNetTrainer_Xepochs_NoMirroring  # PyInstaller hook
    # brain_structures (Dataset409) 等任务不支持 --fast; 按任务自动选择
    fast = task in ("total", "total_v3", "total_mr", "body")
    seg_nifti = totalsegmentator(nii_path, task=task, fast=fast, device="gpu", quiet=True, output_type="nifti")

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


def _apply_nnunet_serial_patches():
    """Windows/GUI 兼容补丁：nnU-Net 推理路径里的 multiprocessing.Pool（spawn）在
    Qt 线程/非 __main__ 上下文调用会无限 crash-loop（worker 重导入整个 GUI），
    导致 GPU 推理无法启动。这里把两处 Pool 替换为串行实现。"""
    try:
        import nnunetv2.inference.predict_from_raw_data as pfr
        import nnunetv2.utilities.utils as u
        from batchgenerators.utilities.file_operations import subfiles

        if getattr(u.create_lists_from_splitted_dataset_folder, "_serial_patched", False):
            return
        u.create_paths_fn = u.create_paths_fn  # keep reference stable

        def _create_lists_serial(folder, file_ending, identifiers=None, num_processes=12):
            if identifiers is None:
                identifiers = u.get_identifiers_from_splitted_dataset_folder(folder, file_ending)
            files = subfiles(folder, suffix=file_ending, join=False, sort=True)
            return [u.create_paths_fn(folder, files, file_ending, f) for f in identifiers]

        _create_lists_serial._serial_patched = True
        u.create_lists_from_splitted_dataset_folder = _create_lists_serial
        pfr.create_lists_from_splitted_dataset_folder = _create_lists_serial

        def _predict_from_data_iterator_serial(self, data_iterator, save_probabilities=False,
                                               num_processes_segmentation_export=1):
            import os
            import numpy as np
            import torch
            from nnunetv2.inference.predict_from_raw_data import (
                convert_predicted_logits_to_segmentation_with_correct_shape,
                export_prediction_from_logits,
            )
            ret = []
            for preprocessed in data_iterator:
                data = preprocessed["data"]
                if isinstance(data, str):
                    delfile = data
                    data = torch.from_numpy(np.load(data))
                    os.remove(delfile)
                ofile = preprocessed["ofile"]
                properties = preprocessed["data_properties"]
                prediction = self.predict_logits_from_preprocessed_data(data).cpu().detach().numpy()
                if ofile is not None:
                    ret.append(export_prediction_from_logits(
                        prediction, properties, self.configuration_manager,
                        self.plans_manager, self.dataset_json, ofile, save_probabilities))
                else:
                    ret.append(convert_predicted_logits_to_segmentation_with_correct_shape(
                        prediction, self.plans_manager, self.configuration_manager,
                        self.label_manager, properties, save_probabilities))
            if hasattr(data_iterator, "_finish"):
                try:
                    data_iterator._finish()
                except Exception:
                    pass
            try:
                from nnunetv2.inference.data_iterators import compute_gaussian
                from nnunetv2.utilities.helpers import empty_cache
                compute_gaussian.cache_clear()
                empty_cache(self.device)
            except Exception:
                pass
            return ret

        pfr.nnUNetPredictor.predict_from_data_iterator = _predict_from_data_iterator_serial
    except Exception:
        pass


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
