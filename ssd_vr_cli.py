#!/usr/bin/env python3
"""
SSD+VR CLI — 无头渲染 + 语义分割自动化工具
────────────────────────────────────────────
用法:
  python ssd_vr_cli.py --input /path/to/DICOM --mode cinematic --preset CT-AAA --save-screenshot
  python ssd_vr_cli.py --input /path/to/DICOM --seg --save-seg-masks --save-seg-json
  python ssd_vr_cli.py --input /path/to/DICOM --animate 72 --mode cinematic
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import typing as t
from pathlib import Path

import numpy as np

root_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, root_dir)

# ─── 延迟导入：渲染模块在需要时才加载，允许 --help / --list-presets 无需 VTK/PySide6 ───
vtk = None          # type: ignore[assignment]
sitk = None         # type: ignore[assignment]
QtCore = None       # type: ignore[assignment]
QApplication = None # type: ignore[assignment]

def _import_render_core():
    """延迟导入 ssd_vr_viewer 渲染函数 + VTK + PySide6。仅在需要加载/渲染时调用。"""
    global vtk, sitk, QtCore, QApplication
    if vtk is not None:
        return
    try:
        import vtk as _vtk;        vtk = _vtk
        import SimpleITK as _sitk; sitk = _sitk
        from PySide6 import QtCore as _QtCore;                 QtCore = _QtCore
        from PySide6.QtWidgets import QApplication as _QApp;   QApplication = _QApp
        from ssd_vr_viewer import (  # type: ignore[import-not-found]
            build_reader as _br,
            FusionController as _fc,
            ErCoreWrapper as _ew,
            make_opacity as _mo,
            make_color as _mc,
            interp_piecewise as _ip,
            interp_color as _ic,
        )
        g = globals()
        g["build_reader"] = _br
        g["FusionController"] = _fc
        g["ErCoreWrapper"] = _ew
        g["make_opacity"] = _mo
        g["make_color"] = _mc
        g["interp_piecewise"] = _ip
        g["interp_color"] = _ic
    except ImportError as e:
        sys.exit(
            f"Error: Cannot import SSD+VR rendering module.\n"
            f"  {e}\n"
            f"  This CLI requires the pvpython environment (ParaView + PyQt5).\n"
            f"  Try: pvpython ssd_vr_cli.py --input /path/to/DICOM ...\n"
            f"  --help and --list-presets work without rendering imports."
        )

# ══════════════════════════ 渲染模式定义 ══════════════════════════
RENDERING_MODES: dict[str, int] = {
    "stable":           0,
    "hd_surface":       1,
    "cinematic":        2,
    "nature_channels":  3,
    "figure8_channels": 4,
    "layer_channel":    5,
    "frangi_channel":   6,
    "bone_mono":        7,
    "2dtf":             8,
    "spectral":         9,
    "exposure_render":  10,
    "dual_volume":      11,
}
MODES_BY_INDEX: dict[int, str] = {v: k for k, v in RENDERING_MODES.items()}

# ══════════════════════════ 灯光预设 ══════════════════════════
LIGHT_PRESETS: dict[str, dict] = {
    "bright": {
        "key_pos": (300.0, -400.0, 600.0),  "key_dir": (-0.4, 0.5, -0.78),
        "key_color": (1.0, 1.0, 1.0),       "key_mult": 2.5,  "key_size": (0.5, 0.5),
        "fill_pos": (-200.0, 300.0, 200.0),  "fill_dir": (0.45, -0.78, -0.43),
        "fill_color": (1.0, 1.0, 1.0),       "fill_mult": 1.2, "fill_size": (1.5, 1.5),
        "rim_pos": (-500.0, -200.0, -100.0), "rim_dir": (0.9, 0.3, 0.33),
        "rim_color": (1.0, 0.92, 0.84),      "rim_mult": 1.8, "rim_size": (0.3, 0.3),
    },
    "ambient": {
        "key_pos": (200.0, -300.0, 500.0),   "key_dir": (-0.3, 0.45, -0.83),
        "key_color": (1.0, 1.0, 0.98),       "key_mult": 1.8,  "key_size": (0.8, 0.8),
        "fill_pos": (-150.0, 250.0, 250.0),  "fill_dir": (0.37, -0.65, -0.67),
        "fill_color": (0.90, 0.92, 1.0),     "fill_mult": 1.5, "fill_size": (2.0, 2.0),
        "rim_pos": (-400.0, -150.0, -50.0),  "rim_dir": (0.85, 0.35, 0.40),
        "rim_color": (1.0, 0.95, 0.88),      "rim_mult": 2.0, "rim_size": (0.4, 0.4),
    },
    "dramatic": {
        "key_pos": (400.0, -500.0, 700.0),   "key_dir": (-0.5, 0.58, -0.65),
        "key_color": (1.0, 1.0, 1.0),        "key_mult": 3.5,  "key_size": (0.3, 0.3),
        "fill_pos": (-200.0, 300.0, 150.0),  "fill_dir": (0.42, -0.75, -0.50),
        "fill_color": (0.78, 0.82, 1.0),     "fill_mult": 0.8, "fill_size": (2.5, 2.5),
        "rim_pos": (-600.0, -250.0, -200.0), "rim_dir": (0.92, 0.28, 0.25),
        "rim_color": (1.0, 0.88, 0.72),      "rim_mult": 2.8, "rim_size": (0.2, 0.2),
    },
}

# ══════════════════════════ 相机预设 ══════════════════════════
CAMERA_PRESETS: dict[str, dict] = {
    "coronal": {
        "pos": (0.0, -800.0, 0.0), "target": (0.0, 0.0, 0.0), "up": (0.0, 0.0, 1.0),
    },
    "coronal_rear": {
        "pos": (0.0, 800.0, 0.0), "target": (0.0, 0.0, 0.0), "up": (0.0, 0.0, 1.0),
    },
    "sagittal": {
        "pos": (800.0, 0.0, 0.0), "target": (0.0, 0.0, 0.0), "up": (0.0, 0.0, 1.0),
    },
    "sagittal_rear": {
        "pos": (-800.0, 0.0, 0.0), "target": (0.0, 0.0, 0.0), "up": (0.0, 0.0, 1.0),
    },
    "axial": {
        "pos": (0.0, 0.0, 800.0), "target": (0.0, 0.0, 0.0), "up": (0.0, 1.0, 0.0),
    },
    "three_quarter": {
        "pos": (300.0, -600.0, 400.0), "target": (0.0, 0.0, 0.0), "up": (-0.3, 0.4, 0.85),
    },
    "front_top": {
        "pos": (0.0, -600.0, 400.0), "target": (0.0, 0.0, 0.0), "up": (0.0, 0.4, 0.9),
    },
}


# ══════════════════════════ Presets 加载 ══════════════════════════
def load_slicer_presets() -> dict:
    """从 presets.xml 加载 31 个 Slicer 预设。"""
    import xml.etree.ElementTree as ET
    presets: dict = {}
    preset_file = os.path.join(root_dir, "presets.xml")
    if not os.path.exists(preset_file):
        return presets
    tree = ET.parse(preset_file)
    for vp in tree.getroot().findall("VolumeProperty"):
        name = vp.get("name")
        if not name:
            continue
        so_parts = vp.get("scalarOpacity", "").split()
        opacity_pts = []
        if so_parts:
            num_pts = int(so_parts[0])
            idx = 1
            for _ in range(num_pts):
                if idx + 1 < len(so_parts):
                    opacity_pts.append((float(so_parts[idx]), float(so_parts[idx + 1])))
                    idx += 2
        ct_parts = vp.get("colorTransfer", "").split()
        color_pts = []
        if ct_parts:
            num_pts = int(ct_parts[0])
            idx = 1
            for _ in range(num_pts):
                if idx + 3 < len(ct_parts):
                    color_pts.append((float(ct_parts[idx]), float(ct_parts[idx + 1]),
                                      float(ct_parts[idx + 2]), float(ct_parts[idx + 3])))
                    idx += 4
        presets[name] = {
            "opacity": opacity_pts,
            "color": color_pts,
            "ambient": float(vp.get("ambient", 0.1)),
            "diffuse": float(vp.get("diffuse", 0.7)),
            "specular": float(vp.get("specular", 0.3)),
            "specularPower": float(vp.get("specularPower", 20.0)),
        }
    return presets


SLICER_PRESETS = load_slicer_presets()


# ═══════════════════ 模式→光照/材质配置 ═══════════════════

def _configure_ssd_property(mode: str, prop: vtk.vtkVolumeProperty) -> None:
    mode_cfg = {
        "cinematic":        (0.08, 0.72, 0.50, 50.0),
        "exposure_render":  (0.08, 0.72, 0.50, 50.0),
        "dual_volume":      (0.08, 0.72, 0.50, 50.0),
        "nature_channels":  (0.15, 0.60, 0.60, 40.0),
        "figure8_channels": (0.12, 0.65, 0.55, 50.0),
        "layer_channel":    (0.08, 0.55, 0.20, 16.0),
        "frangi_channel":   (0.06, 0.50, 0.18, 12.0),
        "bone_mono":        (0.18, 0.72, 0.30, 25.0),
    }
    cr_modes = {"hd_surface", "cinematic", "nature_channels", "spectral",
                "dual_volume", "exposure_render", "figure8_channels",
                "layer_channel", "frangi_channel", "bone_mono"}
    if mode in cr_modes:
        prop.ShadeOn()
        cfg = mode_cfg.get(mode, (0.10, 0.75, 0.38, 24.0))
        prop.SetAmbient(cfg[0])
        prop.SetDiffuse(cfg[1])
        prop.SetSpecular(cfg[2])
        prop.SetSpecularPower(cfg[3])
    else:
        prop.ShadeOff()


def _configure_vr_property(mode: str, prop: vtk.vtkVolumeProperty,
                           step_factor: float = 0.1, cr_denoise: float = 0.0) -> None:
    if mode in ("cinematic", "spectral", "dual_volume", "exposure_render", "figure8_channels"):
        prop.ShadeOn()
        prop.SetAmbient(0.35)
        prop.SetDiffuse(0.85)
        prop.SetSpecular(0.35)
        prop.SetSpecularPower(40.0)
        dist = max(0.4, min(1.6, 0.5 + 2.0 * step_factor)) + cr_denoise * 0.8
        prop.SetScalarOpacityUnitDistance(dist)
    elif mode == "layer_channel":
        prop.ShadeOn()
        prop.SetAmbient(0.30)
        prop.SetDiffuse(0.88)
        prop.SetSpecular(0.12)
        prop.SetSpecularPower(8.0)
        dist = max(0.3, min(1.4, 0.4 + 2.0 * step_factor)) + cr_denoise * 0.6
        prop.SetScalarOpacityUnitDistance(dist)
    elif mode == "frangi_channel":
        prop.ShadeOn()
        prop.SetAmbient(0.28)
        prop.SetDiffuse(0.90)
        prop.SetSpecular(0.10)
        prop.SetSpecularPower(8.0)
        dist = max(0.3, min(1.4, 0.4 + 2.0 * step_factor)) + cr_denoise * 0.5
        prop.SetScalarOpacityUnitDistance(dist)
    elif mode == "bone_mono":
        prop.ShadeOn()
        prop.SetAmbient(0.12)
        prop.SetDiffuse(0.55)
        prop.SetSpecular(0.85)
        prop.SetSpecularPower(120.0)
        dist = max(0.3, min(1.4, 0.4 + 2.0 * step_factor)) + cr_denoise * 0.5
        prop.SetScalarOpacityUnitDistance(dist)
    elif mode == "2dtf":
        prop.ShadeOn()
        prop.SetAmbient(0.15)
        prop.SetDiffuse(0.78)
        prop.SetSpecular(0.42)
        prop.SetSpecularPower(45.0)
        dist = max(0.3, min(1.4, 0.4 + 2.0 * step_factor)) + cr_denoise * 0.5
        prop.SetScalarOpacityUnitDistance(dist)
    elif mode == "nature_channels":
        prop.ShadeOn()
        prop.SetAmbient(0.20)
        prop.SetDiffuse(0.65)
        prop.SetSpecular(0.55)
        prop.SetSpecularPower(40.0)
        dist = max(0.3, min(1.4, 0.4 + 2.0 * step_factor)) + cr_denoise * 0.6
        prop.SetScalarOpacityUnitDistance(dist)
    else:
        prop.ShadeOff()


# ══════════════════════════ OffscreenRenderer ══════════════════════════

class OffscreenRenderer:
    """无头 VTK 体积渲染器 —— 不需要显示器。"""

    def __init__(
        self,
        mode: str = "stable",
        preset: str | None = None,
        ssd_opacity: float = 0.5,
        vr_opacity: float = 0.8,
        camera: str = "coronal",
        background: str = "light",
        window: tuple | None = None,
        ambient: float | None = None,
        diffuse: float | None = None,
        specular: float | None = None,
        specular_power: float | None = None,
        er_wrapper: t.Any = None,
        cpu_render: bool = False,
    ):
        self.mode = mode
        self.preset_name = preset
        self.ssd_opacity = ssd_opacity
        self.vr_opacity = vr_opacity
        self.camera_name = camera
        self.cpu_render = cpu_render
        self.er_wrapper = er_wrapper

        # ── VTK 管线 ──
        self.render_window = vtk.vtkRenderWindow()
        self.render_window.SetOffScreenRendering(1)
        self.renderer = vtk.vtkRenderer()
        self.render_window.AddRenderer(self.renderer)

        self.ssd_volume: vtk.vtkVolume | None = None
        self.vr_volume: vtk.vtkVolume | None = None
        self.fusion: FusionController | None = None
        self.image_data: vtk.vtkImageData | None = None
        self._bounds: tuple = (0, 0, 0, 0, 0, 0)

        # ── 背景色 ──
        if background.startswith("#"):
            c = _hex_to_rgb(background)
            self.renderer.SetBackground(c[0] / 255, c[1] / 255, c[2] / 255)
        elif background == "dark":
            self.renderer.SetBackground(0.05, 0.05, 0.08)
        else:
            self.renderer.SetBackground(0.94, 0.95, 0.97)

        # ── 相机 ──
        self._apply_camera(camera)

        # ── 自定义光照/材质（覆盖默认） ──
        self._custom_ambient = ambient
        self._custom_diffuse = diffuse
        self._custom_specular = specular
        self._custom_specular_power = specular_power

    # ────────── 体积设置 ──────────

    def set_volume(self, image_data: vtk.vtkImageData) -> None:
        self.image_data = image_data
        bounds = image_data.GetBounds()
        self._bounds = bounds

        # ── SSD 体积 ──
        ssd_mapper = vtk.vtkSmartVolumeMapper() if not self.cpu_render else \
                     vtk.vtkFixedPointVolumeRayCastMapper()
        if not self.cpu_render:
            ssd_mapper.SetRequestedRenderModeToGPU()

        producer = vtk.vtkTrivialProducer()
        producer.SetOutput(image_data)
        ssd_shallow = vtk.vtkImageData()
        ssd_shallow.ShallowCopy(image_data)
        # 连接管线
        ssd_producer = vtk.vtkTrivialProducer()
        ssd_producer.SetOutput(ssd_shallow)
        ssd_mapper.SetInputConnection(ssd_producer.GetOutputPort())

        ssd_prop = vtk.vtkVolumeProperty()
        ssd_prop.SetInterpolationTypeToLinear()

        # SSD 骨骼 TF（默认）
        if self.preset_name and self.preset_name in SLICER_PRESETS:
            preset = SLICER_PRESETS[self.preset_name]
            self.ssd_opacity_pts = preset["opacity"]
            self.ssd_color_pts = preset["color"]
            if self._custom_ambient is None:
                ssd_prop.SetAmbient(preset["ambient"])
                ssd_prop.SetDiffuse(preset["diffuse"])
                ssd_prop.SetSpecular(preset["specular"])
                ssd_prop.SetSpecularPower(preset["specularPower"])
        else:
            self.ssd_opacity_pts = [(-1000, 0.0), (200, 0.0), (300, 0.3),
                                     (400, 0.6), (800, 0.8), (1300, 1.0), (3000, 1.0)]
            self.ssd_color_pts = [
                (-1000, 0.0, 0.0, 0.0), (100, 0.4, 0.4, 0.4),
                (320, 0.7, 0.65, 0.6), (800, 0.88, 0.82, 0.75),
                (1300, 0.95, 0.9, 0.85), (3000, 1.0, 1.0, 1.0),
            ]

        if self._custom_ambient is not None:
            ssd_prop.SetAmbient(self._custom_ambient)
            ssd_prop.SetDiffuse(self._custom_diffuse or 0.7)
            ssd_prop.SetSpecular(self._custom_specular or 0.3)
            ssd_prop.SetSpecularPower(self._custom_specular_power or 20.0)

        _configure_ssd_property(self.mode, ssd_prop)
        ssd_prop.SetScalarOpacity(make_opacity(self.ssd_opacity_pts, self.ssd_opacity))
        ssd_prop.SetColor(make_color(self.ssd_color_pts))

        self.ssd_volume = vtk.vtkVolume()
        self.ssd_volume.SetMapper(ssd_mapper)
        self.ssd_volume.SetProperty(ssd_prop)

        # ── VR 体积 ──
        vr_mapper = vtk.vtkSmartVolumeMapper() if not self.cpu_render else \
                    vtk.vtkFixedPointVolumeRayCastMapper()
        if not self.cpu_render:
            vr_mapper.SetRequestedRenderModeToGPU()

        vr_producer = vtk.vtkTrivialProducer()
        vr_shallow = vtk.vtkImageData()
        vr_shallow.ShallowCopy(image_data)
        vr_producer.SetOutput(vr_shallow)
        vr_mapper.SetInputConnection(vr_producer.GetOutputPort())

        vr_prop = vtk.vtkVolumeProperty()
        vr_prop.SetInterpolationTypeToLinear()

        self.vr_opacity_pts = [
            (-1000, 0.0), (140, 0.0), (160, 0.15), (200, 0.35),
            (280, 0.55), (400, 0.70), (550, 0.80), (3000, 0.80),
        ]
        self.vr_color_pts = [
            (-1000, 0.0, 0.0, 0.0), (150, 1.0, 0.55, 0.0),
            (250, 1.0, 0.80, 0.20), (400, 1.0, 0.92, 0.50),
            (550, 1.0, 0.96, 0.0), (3000, 1.0, 1.0, 0.90),
        ]

        # 应用预设到 VR 层（覆盖上述默认值）
        if self.preset_name and self.preset_name in SLICER_PRESETS:
            preset = SLICER_PRESETS[self.preset_name]
            self.vr_opacity_pts = preset["opacity"]
            self.vr_color_pts = preset["color"]

        _configure_vr_property(self.mode, vr_prop)
        vr_prop.SetScalarOpacity(make_opacity(self.vr_opacity_pts, self.vr_opacity))
        vr_prop.SetColor(make_color(self.vr_color_pts))

        self.vr_volume = vtk.vtkVolume()
        self.vr_volume.SetMapper(vr_mapper)
        self.vr_volume.SetProperty(vr_prop)

        # ── 双层渲染 ──
        if self.mode == "dual_volume":
            self.renderer.AddViewProp(self.vr_volume)
            self.renderer.AddViewProp(self.ssd_volume)
        elif self.mode == "bioicons":
            self.vr_volume.SetVisibility(False)
            self.renderer.AddViewProp(self.ssd_volume)
        else:
            self.renderer.AddViewProp(self.ssd_volume)
            self.renderer.AddViewProp(self.vr_volume)

        # ── Fusion Controller ──
        self.fusion = FusionController(
            ssd_volume=self.ssd_volume,
            vr_volume=self.vr_volume,
            ssd_points=self.ssd_opacity_pts,
            vr_points=self.vr_opacity_pts,
            ssd_color_points=self.ssd_color_pts,
            vr_color_points=self.vr_color_pts,
            fused_volume=None,
        )
        self.fusion.update(self.ssd_opacity, self.vr_opacity)

        self.renderer.ResetCamera()
        self._apply_camera(self.camera_name)

    # ────────── 相机 ──────────

    def _apply_camera(self, camera: str) -> None:
        cam = CAMERA_PRESETS.get(camera, CAMERA_PRESETS["coronal"])
        camera_obj = self.renderer.GetActiveCamera()
        camera_obj.SetPosition(cam["pos"])
        camera_obj.SetFocalPoint(cam["target"])
        camera_obj.SetViewUp(cam["up"])
        self.renderer.ResetCameraClippingRange()

    def set_camera_angles(self, pos: tuple, target: tuple, up: tuple) -> None:
        cam = self.renderer.GetActiveCamera()
        cam.SetPosition(pos)
        cam.SetFocalPoint(target)
        cam.SetViewUp(up)
        self.renderer.ResetCameraClippingRange()

    def rotate_camera(self, azimuth: float, elevation: float) -> None:
        """旋转相机（单位：度）。"""
        cam = self.renderer.GetActiveCamera()
        cam.Azimuth(azimuth)
        cam.Elevation(elevation)
        self.renderer.ResetCameraClippingRange()

    # ────────── 屏幕尺寸 ──────────

    def set_size(self, w: int, h: int) -> None:
        self.render_window.SetSize(w, h)

    # ────────── 渲染 ──────────

    def render(self) -> None:
        self.render_window.Render()

    # ────────── 截图 ──────────

    def screenshot_to_array(self) -> np.ndarray:
        """渲染当前帧并返回 RGBA numpy 数组 (h, w, 4, uint8)。"""
        self.render_window.Render()
        w2i = vtk.vtkWindowToImageFilter()
        w2i.SetInput(self.render_window)
        w2i.SetInputBufferTypeToRGBA()
        w2i.ReadFrontBufferOff()
        w2i.Update()
        dims = w2i.GetOutput().GetDimensions()
        np.copyto(np.zeros((dims[1], dims[0], 4), dtype=np.uint8),
                  vtk.util.numpy_support.vtk_to_numpy(
                      w2i.GetOutput().GetPointData().GetScalars()).reshape(dims[1], dims[0], -1))
        return vtk.util.numpy_support.vtk_to_numpy(
            w2i.GetOutput().GetPointData().GetScalars()
        ).reshape(dims[1], dims[0], 4).copy()

    def screenshot(self, path: str, size: tuple[int, int] = (1920, 1080)) -> str:
        """保存 PNG 截图。"""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.set_size(*size)
        self.render_window.Render()
        w2i = vtk.vtkWindowToImageFilter()
        w2i.SetInput(self.render_window)
        w2i.SetInputBufferTypeToRGBA()
        w2i.ReadFrontBufferOff()
        w2i.Update()
        writer = vtk.vtkPNGWriter()
        writer.SetFileName(path)
        writer.SetInputConnection(w2i.GetOutputPort())
        writer.Write()
        return path

    @property
    def bounds(self) -> tuple:
        return self._bounds


# ══════════════════════════ 导出工具 ══════════════════════════


class ScreenshotExporter:
    def __init__(self, renderer: OffscreenRenderer):
        self.r = renderer

    def save(self, path: str, size: tuple = (1920, 1080)) -> str:
        return self.r.screenshot(path, size)


class MIPExporter:
    def __init__(self, renderer: OffscreenRenderer):
        self.r = renderer

    def export_all(self, out_dir: str, size: tuple = (1920, 1080)) -> list[str]:
        os.makedirs(out_dir, exist_ok=True)
        results = []
        for name, cam in [("coronal", "coronal"), ("sagittal", "sagittal"),
                          ("axial", "axial")]:
            self.r._apply_camera(cam)
            self.r.render()
            path = os.path.join(out_dir, f"mip_{name}.png")
            self.r.screenshot(path, size)
            results.append(path)
        return results


class AnimationExporter:
    def __init__(self, renderer: OffscreenRenderer):
        self.r = renderer

    def rotate(
        self, frames: int = 72, out_dir: str = "animation", size: tuple = (1920, 1080),
        axis: str = "y"
    ) -> list[str]:
        os.makedirs(out_dir, exist_ok=True)
        delta = 360.0 / frames
        result = []
        for i in range(frames):
            if axis == "y":
                self.r.rotate_camera(delta, 0.0)
            elif axis == "x":
                self.r.rotate_camera(0.0, delta)
            self.r.render()
            path = os.path.join(out_dir, f"frame_{i:04d}.png")
            self.r.screenshot(path, size)
            result.append(path)
            if hasattr(sys.stdout, "reconfigure"):
                print(f"\r  [{i+1}/{frames}]", end="", flush=True)
        print()
        return result


class MultiresExporter:
    def __init__(self, renderer: OffscreenRenderer, image_data: vtk.vtkImageData):
        self.r = renderer
        self.image_data = image_data

    def export(
        self, out_dir: str, size: tuple = (1920, 1080),
        scales: list[tuple[int, str]] | None = None,
    ) -> list[str]:
        if scales is None:
            scales = [(2048, "full"), (1024, "half"), (512, "quart")]
        os.makedirs(out_dir, exist_ok=True)
        from scipy.ndimage import zoom
        arr = vtk.util.numpy_support.vtk_to_numpy(
            self.image_data.GetPointData().GetScalars()
        ).reshape(self.image_data.GetDimensions()[::-1])
        results = []
        target_max = min(arr.shape)
        for res, label in scales:
            if target_max < res:
                scale_factor = max(1.0, res / target_max)
                down_arr = zoom(arr.astype(np.float32), 1.0 / scale_factor, order=1).astype(arr.dtype)
            else:
                scale_factor = target_max / res
                down_arr = zoom(arr.astype(np.float32), 1.0 / scale_factor, order=1).astype(arr.dtype)
            down_img = vtk.vtkImageData()
            dims = down_arr.shape[::-1]
            down_img.SetDimensions(*dims)
            down_img.SetSpacing(
                self.image_data.GetSpacing()[0] * scale_factor,
                self.image_data.GetSpacing()[1] * scale_factor,
                self.image_data.GetSpacing()[2] * scale_factor,
            )
            down_img.SetOrigin(self.image_data.GetOrigin())
            vtka = vtk.util.numpy_support.numpy_to_vtk(
                down_arr.ravel(), deep=True, array_type=vtk.VTK_SHORT
            )
            down_img.GetPointData().SetScalars(vtka)
            new_r = OffscreenRenderer(
                mode=self.r.mode, preset=self.r.preset_name,
                ssd_opacity=self.r.ssd_opacity, vr_opacity=self.r.vr_opacity,
                camera=self.r.camera_name,
                background="light", cpu_render=self.r.cpu_render,
            )
            new_r.set_volume(down_img)
            path = os.path.join(out_dir, f"vr_{res}_{label}.png")
            new_r.screenshot(path, size)
            results.append(path)
        return results


# ══════════════════════════ 分割导出 ══════════════════════════


class ROIMetadataExporter:
    @staticmethod
    def save_json(
        roi_results: list, label_map: np.ndarray | None, path: str,
    ) -> str:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        data = {
            "total_rois": 0,
            "bones": [], "organs": [], "vessels": [],
            "label_map_shape": list(label_map.shape) if label_map is not None else [],
            "label_map_dtype": str(label_map.dtype) if label_map is not None else "",
        }
        for region in roi_results:
            for cat, cat_name in [("bones", "骨骼"), ("organs", "组织"), ("vessels", "血管")]:
                blocks = getattr(region, cat, []) if hasattr(region, cat) else region.get(cat, [])
                for blk in blocks:
                    entry = {
                        "name": getattr(blk, "anatomical_name", blk.get("anatomical_name", "")),
                        "label_id": getattr(blk, "label_id", blk.get("label_id", 0)),
                        "volume_cm3": round(getattr(blk, "volume_cm3", blk.get("volume_cm3", 0)), 3),
                        "voxel_count": int(getattr(blk, "voxel_count", blk.get("voxel_count", 0))),
                        "bbox_z": list(getattr(blk, "bbox_z", blk.get("bbox_z", (0, 0)))),
                        "bbox_y": list(getattr(blk, "bbox_y", blk.get("bbox_y", (0, 0)))),
                        "bbox_x": list(getattr(blk, "bbox_x", blk.get("bbox_x", (0, 0)))),
                    }
                    data[cat].append(entry)
                    data["total_rois"] += 1
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return path


class MaskExporter:
    def __init__(self, label_map: np.ndarray, roi_label_map: dict | None = None):
        self.label_map = label_map
        self._label_map = roi_label_map

    def save_all(self, out_dir: str) -> str:
        """保存完整 label_map.npz 到输出目录。"""
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, "label_map.npz")
        np.savez_compressed(path, label_map=self.label_map)
        return path

    def save_per_class(
        self, out_dir: str, classes: list[int] | None = None,
    ) -> list[str]:
        os.makedirs(out_dir, exist_ok=True)
        unique = np.unique(self.label_map)
        if classes is not None:
            unique = [c for c in unique if c in set(classes)]
        results = []
        for cls_id in unique:
            if cls_id == 0:
                continue
            mask = (self.label_map == cls_id).astype(np.uint8)
            if mask.sum() == 0:
                continue
            name = self._get_name(cls_id) if self._label_map else f"class_{cls_id}"
            path = os.path.join(out_dir, f"{name}.npz")
            np.savez_compressed(path, mask=mask)
            results.append(path)
        return results

    def _get_name(self, cls_id: int) -> str:
        if self._label_map:
            entry = self._label_map.get(cls_id, ("", ""))
            return f"{cls_id:03d}_{entry[0]}" if isinstance(entry, tuple) else f"{cls_id:03d}"
        return f"class_{cls_id:03d}"


# ══════════════════════════ Summary Reporter ══════════════════════════

class SummaryReporter:
    @staticmethod
    def print_start(args: argparse.Namespace, volume_shape: tuple, spacing: tuple) -> None:
        print(f"[SSD+VR CLI] Loading DICOM: {args.input}")
        print(f"[SSD+VR CLI] Volume: {volume_shape[2]}×{volume_shape[1]}×{volume_shape[0]} "
              f"| spacing={spacing[0]:.3f}×{spacing[1]:.3f}×{spacing[2]:.3f}mm")
        print(f"[SSD+VR CLI] Mode: {args.mode} | Preset: {args.preset or 'default'} "
              f"| Render: {list(args.render_size)}")
        print(f"[SSD+VR CLI] Denoise: {args.denoise} | CLAHE: {args.clahe} "
              f"| Frangi: {args.frangi} | CPU: {args.cpu}")

    @staticmethod
    def print_seg_stats(roi_results: list, label_map: np.ndarray) -> None:
        n_bones = n_organs = n_vessels = 0
        vol_bones = vol_organs = vol_vessels = 0.0
        for region in roi_results:
            for cat in ["bones", "organs", "vessels"]:
                blocks = getattr(region, cat, []) if hasattr(region, cat) else region.get(cat, [])
                for blk in blocks:
                    vol = getattr(blk, "volume_cm3", blk.get("volume_cm3", 0))
                    if cat == "bones":
                        n_bones += 1; vol_bones += vol
                    elif cat == "organs":
                        n_organs += 1; vol_organs += vol
                    else:
                        n_vessels += 1; vol_vessels += vol
        print(f"[SSD+VR CLI] Semantic segmentation: {np.unique(label_map).size - 1} classes detected")
        print(f"    Bone:   {n_bones} structures, {vol_bones:.1f} cm³")
        print(f"    Organ:  {n_organs} structures, {vol_organs:.1f} cm³")
        print(f"    Vessel: {n_vessels} structures, {vol_vessels:.1f} cm³")

    @staticmethod
    def print_done(start_time: float, output_dir: str) -> None:
        elapsed = time.time() - start_time
        print(f"[SSD+VR CLI] Done. Output: {output_dir}   ⏱ {elapsed:.1f}s total")


# ══════════════════════════ Helpers ══════════════════════════

def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


# ══════════════════════════ 主流程 ══════════════════════════

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="SSD+VR CLI — 无头体积渲染 + 语义分割自动化",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --input /data/DICOM --mode cinematic --save-screenshot
  %(prog)s --input /data/DICOM --seg --save-seg-masks --save-seg-json
  %(prog)s --input /data/DICOM --animate 72 --mode cinematic --preset CT-AAA
        """,
    )

    # ── 输入 ──
    p.add_argument("--input", default="", help="DICOM 目录或单文件路径（单文件夹模式）")
    p.add_argument("--batch", default="", metavar="DIR", help="批量模式: 父目录，自动扫描所有 DICOM 子文件夹")
    p.add_argument("--batch-pattern", default="*", metavar="GLOB",
                   help="批量模式文件夹名过滤 (default: *)")
    p.add_argument("--output", default="./ssd_vr_output", help="输出根目录")

    # ── 渲染 ──
    p.add_argument("--mode", default="cinematic", choices=sorted(RENDERING_MODES),
                   help="渲染模式 (default: cinematic)")
    p.add_argument("--preset", default=None,
                   help=f"Slicer 预设名 (e.g. {', '.join(sorted(SLICER_PRESETS)[:6])}...)")
    p.add_argument("--window", nargs=2, type=int, default=None,
                   help="窗宽 窗位 (HU), e.g. 900 100")
    p.add_argument("--ssd-opacity", type=float, default=0.5, help="SSD 骨骼层不透明度")
    p.add_argument("--vr-opacity", type=float, default=0.8, help="VR 血管层不透明度")
    p.add_argument("--camera", default="coronal", choices=sorted(CAMERA_PRESETS),
                   help="预设相机角度 (default: coronal)")
    p.add_argument("--background", default="light",
                   help="背景: light|dark|#RRGGBB (default: light)")
    p.add_argument("--ambient", type=float, default=None, help="覆盖 Ambient 系数")
    p.add_argument("--diffuse", type=float, default=None, help="覆盖 Diffuse 系数")
    p.add_argument("--specular", type=float, default=None, help="覆盖 Specular 系数")
    p.add_argument("--specular-power", type=float, default=None, help="覆盖 SpecularPower")

    # ── 预处理 ──
    p.add_argument("--denoise", default="gaussian", choices=["gaussian", "nlm", "off"],
                   help="去噪方法 (default: gaussian)")
    p.add_argument("--clahe", action="store_true", help="启用 CLAHE 自适应直方图均衡")
    p.add_argument("--frangi", action="store_true", help="启用 Frangi 血管增强")

    # ── 输出导出 ──
    p.add_argument("--render-size", nargs=2, type=int, default=[1920, 1080],
                   help="渲染分辨率 W H (default: 1920 1080)")
    p.add_argument("--save-screenshot", action="store_true", help="保存主渲染截图")
    p.add_argument("--save-mip", action="store_true", help="保存 MIP 投影（冠状面+矢状面+轴位）")
    p.add_argument("--save-multires", action="store_true",
                   help="多分辨率对比渲染 (2048/1024/512)")
    p.add_argument("--animate", type=int, default=0, metavar="N",
                   help="导出 N 帧旋转动画 (PNG)")
    p.add_argument("--animate-axis", default="y", choices=["x", "y"],
                   help="动画旋转轴 (default: y)")

    # ── 语义分割 ──
    p.add_argument("--seg", action="store_true", help="启用 TotalSegmentator v2 语义分割")
    p.add_argument("--save-seg-masks", action="store_true", help="保存分割掩模 (.npz)")
    p.add_argument("--save-seg-json", action="store_true", help="保存 ROI 元数据 (JSON)")

    # ── 其他 ──
    p.add_argument("--cpu", action="store_true", help="使用 CPU 渲染")
    p.add_argument("--vram", type=float, default=10.0, help="显存阈值 (GB, default: 10)")
    p.add_argument("--list-presets", action="store_true", help="列出所有可用预设后退出")

    return p.parse_args(argv)


def validate_args(args: argparse.Namespace) -> None:
    if not args.input and not args.batch:
        print("Error: either --input or --batch must be specified.", file=sys.stderr)
        sys.exit(1)
    if args.input and not os.path.exists(args.input):
        print(f"Error: input path does not exist: {args.input}", file=sys.stderr)
        sys.exit(1)
    if args.batch and not os.path.exists(args.batch):
        print(f"Error: batch directory does not exist: {args.batch}", file=sys.stderr)
        sys.exit(1)
    if args.input and args.batch:
        print("Error: --input and --batch are mutually exclusive.", file=sys.stderr)
        sys.exit(1)
    if args.mode not in RENDERING_MODES:
        print(f"Error: unknown mode '{args.mode}'. Choices: {sorted(RENDERING_MODES)}",
              file=sys.stderr)
        sys.exit(1)
    if args.preset and args.preset not in SLICER_PRESETS:
        print(f"Warning: unknown preset '{args.preset}'. Using default. "
              f"Available: {sorted(SLICER_PRESETS)[:10]}...", file=sys.stderr)


def _discover_dicom_subdirs(parent: str, pattern: str = "*") -> list[str]:
    """扫描父目录下包含 DICOM 文件的子文件夹。"""
    import fnmatch, glob
    results = []
    for entry in sorted(os.listdir(parent)):
        entry_path = os.path.join(parent, entry)
        if not os.path.isdir(entry_path):
            continue
        if pattern != "*" and not fnmatch.fnmatch(entry, pattern):
            continue
        dcm_files = glob.glob(os.path.join(entry_path, "*.dcm")) +                     glob.glob(os.path.join(entry_path, "*.DCM"))
        if not dcm_files:
            try:
                reader = sitk.ImageSeriesReader()
                dcm_files = reader.GetGDCMSeriesFileNames(entry_path)
            except Exception:
                pass
        if dcm_files:
            results.append(entry_path)
    return results


def process_one(
    input_path: str,
    output_dir: str,
    args: argparse.Namespace,
    batch_label: str = "",
) -> int:
    """处理单个 DICOM 文件夹的完整流程。返回 0 成功，非 0 失败。"""
    t0 = time.time()
    prefix = f"[{batch_label}] " if batch_label else ""
    try:
        # Phase 1: 加载
        is_off = args.denoise == "off"
        print(f"{prefix}Loading: {input_path}")
        image_data, _ = build_reader(
            dicom_path=input_path,
            denoise_method="gaussian" if args.denoise=="gaussian" else ("nlm" if args.denoise=="nlm" else "off"),
            use_clahe=args.clahe,
            use_frangi=args.frangi,
            vram_threshold_gb=args.vram,
            cpu_render=args.cpu,
        )
        dims = image_data.GetDimensions()
        sp = image_data.GetSpacing()
        print(f"{prefix}Volume: {dims[2]}x{dims[1]}x{dims[0]} | sp={sp[0]:.3f}x{sp[1]:.3f}x{sp[2]:.3f}mm")

        # Phase 2: 渲染器
        renderer = OffscreenRenderer(
            mode=args.mode, preset=args.preset,
            ssd_opacity=args.ssd_opacity, vr_opacity=args.vr_opacity,
            camera=args.camera, background=args.background,
            ambient=args.ambient, diffuse=args.diffuse, specular=args.specular,
            specular_power=args.specular_power, cpu_render=args.cpu,
        )
        renderer.set_volume(image_data)
        renderer.set_size(*args.render_size)
        renderer.render()
        os.makedirs(output_dir, exist_ok=True)

        # Phase 3: 导出
        if args.save_screenshot:
            p = os.path.join(output_dir, "render", "screenshot.png")
            renderer.screenshot(p, tuple(args.render_size))
            print(f"{prefix}Screenshot saved")

        if args.save_mip:
            mip_dir = os.path.join(output_dir, "render", "mip")
            MIPExporter(renderer).export_all(mip_dir, tuple(args.render_size))
            print(f"{prefix}MIP exports done")

        if args.animate > 0:
            anim_dir = os.path.join(output_dir, "animation")
            AnimationExporter(renderer).rotate(
                frames=args.animate, out_dir=anim_dir,
                size=tuple(args.render_size), axis=args.animate_axis)
            print(f"{prefix}Animation: {args.animate} frames")

        if args.save_multires:
            mr_dir = os.path.join(output_dir, "render", "multires")
            MultiresExporter(renderer, image_data).export(mr_dir, tuple(args.render_size))
            print(f"{prefix}Multires done")

        # Phase 4: 分割
        if args.seg:
            results, label_map = run_segmentation(input_path, image_data)
            if label_map is not None and args.save_seg_masks:
                seg_dir = os.path.join(output_dir, "segmentation")
                MaskExporter(label_map).save_all(seg_dir)
                print(f"{prefix}Label map saved")
            if results and args.save_seg_json:
                seg_dir = os.path.join(output_dir, "segmentation")
                ROIMetadataExporter.save_json(results, label_map, os.path.join(seg_dir, "roi_metadata.json"))
                print(f"{prefix}ROI metadata saved")
            if results:
                SummaryReporter.print_seg_stats(results, label_map or np.zeros((1,)))

        elapsed = time.time() - t0
        print(f"{prefix}Done ({elapsed:.1f}s)")
        return 0
    except Exception as e:
        print(f"{prefix}ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.list_presets:
        print("Available Slicer presets:")
        for name in sorted(SLICER_PRESETS):
            print(f"  {name}")
        return 0
    validate_args(args)

    _import_render_core()
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)

    # ── 批量模式 ──
    if args.batch:
        subdirs = _discover_dicom_subdirs(args.batch, args.batch_pattern)
        if not subdirs:
            print(f"Error: no DICOM subdirectories found in {args.batch}", file=sys.stderr)
            return 1
        print(f"[SSD+VR CLI] Batch mode: {len(subdirs)} folders found in {args.batch}")
        ok = 0; fail = 0
        t_total = time.time()
        for i, sub in enumerate(subdirs):
            label = f"{i+1}/{len(subdirs)} {os.path.basename(sub)}"
            out_sub = os.path.join(args.output, os.path.basename(sub))
            print(f"\n{'='*60}\n  {label}\n{'='*60}")
            rc = process_one(sub, out_sub, args, batch_label=label)
            if rc == 0: ok += 1
            else: fail += 1
        print(f"\n[SSD+VR CLI] Batch complete: {ok} ok, {fail} failed in {time.time()-t_total:.1f}s total")
        return 0 if fail == 0 else 1

    # ── 单文件夹模式 ──
    return process_one(args.input, args.output, args)


if __name__ == "__main__":
    raise SystemExit(main())
