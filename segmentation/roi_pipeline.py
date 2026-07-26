from __future__ import annotations

import traceback
from typing import List, Optional

import numpy as np
import SimpleITK as sitk
import vtk
from PySide6 import QtCore
from vtkmodules.util import numpy_support

from .roi_types import (
    ROIBlock,
    ROIRegionResult,
)
from .roi_label_map import TOTALSEG_TOTAL
from .detectors.semantic_detector import detect_semantic


class ROIPipeline(QtCore.QThread):
    progress_signal = QtCore.Signal(int, str)
    finished_signal = QtCore.Signal(list, np.ndarray)
    error_signal = QtCore.Signal(str)

    def __init__(
        self,
        image_data: vtk.vtkImageData,
        original_sitk_image: sitk.Image,
        task: str = "total",
    ):
        super().__init__()
        self.image_data = image_data
        self.sitk_image = original_sitk_image
        self.task = task
        self._cancelled = False

        self.spacing = tuple(float(v) for v in original_sitk_image.GetSpacing()[:3])
        self.origin_z = float(original_sitk_image.GetOrigin()[2])

    def cancel(self):
        self._cancelled = True

    def _emit_progress(self, pct: int, msg: str):
        if not self._cancelled:
            self.progress_signal.emit(pct, msg)

    def _bbox_from_mask(self, mask: np.ndarray, z_offset: int = 0) -> tuple:
        coords = np.argwhere(mask)
        if coords.size == 0:
            return (0, 0), (0, 0), (0, 0)
        z_min, y_min, x_min = coords.min(axis=0)
        z_max, y_max, x_max = coords.max(axis=0)
        return (
            (int(z_min) + z_offset, int(z_max) + z_offset + 1),
            (int(y_min), int(y_max) + 1),
            (int(x_min), int(x_max) + 1),
        )

    def _build_block(
        self, region: str, category: str, mask: np.ndarray,
        z_offset: int, spacing: tuple,
        label_id: int = 0, anat_name: str = "",
    ) -> Optional[ROIBlock]:
        vox_count = int(mask.sum())
        if vox_count == 0:
            return None
        sp_mm3 = spacing[0] * spacing[1] * spacing[2]
        volume_cm3 = vox_count * sp_mm3 / 1000.0
        bbox_z, bbox_y, bbox_x = self._bbox_from_mask(mask, z_offset)
        local_z0 = max(0, bbox_z[0] - z_offset)
        local_z1 = max(local_z0 + 1, bbox_z[1] - z_offset)
        cropped_mask = mask[
            local_z0:local_z1,
            bbox_y[0]:bbox_y[1],
            bbox_x[0]:bbox_x[1],
        ].copy()
        z_range_mm = (
            self.origin_z + bbox_z[0] * spacing[2],
            self.origin_z + bbox_z[1] * spacing[2],
        )
        # #region debug-point B:block-summary
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
            'hypothesisId': 'B',
            'location': 'roi_pipeline.py:_build_block',
            'msg': '[DEBUG] roi block extracted',
            'data': {
                'label_id': int(label_id),
                'name': anat_name,
                'category': category,
                'bbox_z': tuple(int(v) for v in bbox_z),
                'bbox_y': tuple(int(v) for v in bbox_y),
                'bbox_x': tuple(int(v) for v in bbox_x),
                'mask_shape': tuple(int(v) for v in cropped_mask.shape),
                'voxel_count': int(vox_count),
                'volume_cm3': float(volume_cm3),
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
        return ROIBlock(
            region=region,
            category=category,
            mask=cropped_mask,
            bbox_z=bbox_z,
            bbox_y=bbox_y,
            bbox_x=bbox_x,
            z_range_mm=z_range_mm,
            volume_cm3=volume_cm3,
            voxel_count=vox_count,
            label_id=label_id,
            anatomical_name=anat_name,
        )

    def run(self):
        try:
            self._emit_progress(0, "TotalSegmentator: 全身117类语义分割...")

            def ts_progress(pct, msg):
                self._emit_progress(pct, msg)

            self._emit_progress(3, "开始语义检测...")
            label_map = detect_semantic(
                self.sitk_image, self.spacing, progress_cb=ts_progress, task=self.task,
            )
            if self._cancelled:
                return

            self._emit_progress(85, "从全局 label_map 提取结构...")

            result = ROIRegionResult(region="全局")
            for idx, (label_id, (anat_name, category)) in enumerate(TOTALSEG_TOTAL.items(), start=1):
                if self._cancelled:
                    return

                mask = (label_map == label_id)
                if mask.sum() == 0:
                    continue

                block = self._build_block(
                    "全局",
                    category,
                    mask,
                    0,
                    self.spacing,
                    label_id=label_id,
                    anat_name=anat_name,
                )
                if block is None:
                    continue

                if category == "bone":
                    result.bones.append(block)
                elif category == "vessel":
                    result.vessels.append(block)
                else:
                    result.tissues.append(block)

                pct = 85 + int(idx / len(TOTALSEG_TOTAL) * 13)
                self._emit_progress(pct, f"结构提取: {anat_name}")

            region_results: List[ROIRegionResult] = []
            if result.bones or result.vessels or result.tissues:
                region_results.append(result)

            if not self._cancelled:
                n_bone = sum(len(r.bones) for r in region_results)
                n_vessel = sum(len(r.vessels) for r in region_results)
                n_tissue = sum(len(r.tissues) for r in region_results)
                self._emit_progress(100, f"完成: {n_bone}骨/{n_vessel}血管/{n_tissue}组织")
                self.finished_signal.emit(region_results, label_map)

        except Exception as e:
            traceback.print_exc()
            self.error_signal.emit(f"{type(e).__name__}: {e}")
