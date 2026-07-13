import argparse
import importlib.util
import os
import sys

# Inject the pv_packages directory into sys.path to allow pvpython to find PyQt5 and SimpleITK
current_dir = os.path.dirname(os.path.abspath(__file__))
pv_packages_dir = os.path.join(current_dir, "pv_packages")
sys.path.insert(0, pv_packages_dir)

# Add the DLL directory for PyQt5 and pv_packages
pyqt5_qt5_bin = os.path.join(pv_packages_dir, "PyQt5", "Qt5", "bin")
pyqt5_root = os.path.join(pv_packages_dir, "PyQt5")
if hasattr(os, "add_dll_directory"):
    if os.path.exists(pyqt5_qt5_bin):
        os.add_dll_directory(pyqt5_qt5_bin)
    if os.path.exists(pyqt5_root):
        os.add_dll_directory(pyqt5_root)
    if os.path.exists(pv_packages_dir):
        os.add_dll_directory(pv_packages_dir)
os.environ["PATH"] = pyqt5_qt5_bin + os.pathsep + pyqt5_root + os.pathsep + pv_packages_dir + os.pathsep + os.environ.get("PATH", "")

# Ensure PyQt5 uses its own plugins instead of ParaView's Qt plugins
qt_plugins_dir = os.path.join(pyqt5_root, "Qt5", "plugins")
if os.path.exists(qt_plugins_dir):
    os.environ["QT_PLUGIN_PATH"] = qt_plugins_dir
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = os.path.join(qt_plugins_dir, "platforms")
    # Tell PyQt5 to ignore ParaView's Qt6 environment variables
    if "QT_ROOT" in os.environ:
        del os.environ["QT_ROOT"]

# Suppress Qt6 invalid metadata warnings from ParaView's DLLs
os.environ["QT_LOGGING_RULES"] = "qt.core.plugin.loader.warning=false;qt.core.library.warning=false"
os.environ["QT_CORE_NO_EXECUTABLE_PATH"] = "1"

from typing import List, Optional, Tuple

import ctypes

ER_DLL_PATH = os.path.join(current_dir, "exposure-render-master", "exposure-render-master", "Source", "build", "Release", "ErCore.dll")
er_core = None
if os.path.exists(ER_DLL_PATH):
    try:
        # Load the directory first to satisfy CUDA runtime dependencies if any
        os.add_dll_directory(os.path.dirname(ER_DLL_PATH))
        er_core = ctypes.CDLL(ER_DLL_PATH)
        er_core.er_create_tracer.restype = ctypes.c_void_p
        er_core.er_create_volume.restype = ctypes.c_void_p
        
        # Camera bindings
        er_core.er_set_tracer_resolution.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        er_core.er_bind_tracer.argtypes = [ctypes.c_void_p]
        er_core.er_get_tracer_id.argtypes = [ctypes.c_void_p]
        er_core.er_get_tracer_id.restype = ctypes.c_int
        er_core.er_set_camera.argtypes = [
            ctypes.c_void_p,
            ctypes.c_float, ctypes.c_float, ctypes.c_float,
            ctypes.c_float, ctypes.c_float, ctypes.c_float,
            ctypes.c_float, ctypes.c_float, ctypes.c_float,
            ctypes.c_float, ctypes.c_float, ctypes.c_float,
            ctypes.c_float, ctypes.c_float
        ]
        
        er_core.er_bind_volume_data.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_float, ctypes.c_float, ctypes.c_float,
            ctypes.c_void_p
        ]
        er_core.er_bind_volume.argtypes = [ctypes.c_void_p]
        
        # ErCore rendering
        er_core.er_render_estimate.argtypes = [ctypes.c_int]
        er_core.er_get_estimate.argtypes = [ctypes.c_int, ctypes.c_void_p]
        er_core.er_clear_opacity_tf.argtypes = [ctypes.c_void_p]
        er_core.er_add_opacity_node.argtypes = [ctypes.c_void_p, ctypes.c_float, ctypes.c_float]
        er_core.er_clear_diffuse_tf.argtypes = [ctypes.c_void_p]
        er_core.er_add_diffuse_node.argtypes = [ctypes.c_void_p, ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float]
        er_core.er_reset_accumulation.argtypes = [ctypes.c_void_p]

        # Light bindings
        er_core.er_create_light.restype = ctypes.c_void_p
        er_core.er_destroy_light.argtypes = [ctypes.c_void_p]
        er_core.er_bind_light.argtypes = [ctypes.c_void_p]
        er_core.er_tracer_add_light.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        er_core.er_tracer_clear_lights.argtypes = [ctypes.c_void_p]
        er_core.er_set_light_properties.argtypes = [
            ctypes.c_void_p,
            ctypes.c_float, ctypes.c_float, ctypes.c_float,
            ctypes.c_float, ctypes.c_float, ctypes.c_float,
            ctypes.c_float, ctypes.c_float, ctypes.c_float,
            ctypes.c_float, ctypes.c_float, ctypes.c_float
        ]
    except Exception as e:
        print(f"Warning: Failed to load ErCore.dll: {e}")

class ErCoreWrapper:
    def __init__(self):
        if not er_core:
            raise RuntimeError("ErCore is not loaded.")
        self.tracer = er_core.er_create_tracer()
        self.volume = er_core.er_create_volume()
        self.lights = []

    def __del__(self):
        if er_core:
            er_core.er_destroy_tracer(self.tracer)
            er_core.er_destroy_volume(self.volume)
            for light in self.lights:
                er_core.er_destroy_light(light)

    def setup_lights(self, key_pos, key_dir, key_color, key_mult, key_size,
                           fill_pos, fill_dir, fill_color, fill_mult, fill_size,
                           rim_pos, rim_dir, rim_color, rim_mult, rim_size):
        # Clear existing lights
        er_core.er_tracer_clear_lights(self.tracer)
        for light in self.lights:
            er_core.er_destroy_light(light)
        self.lights.clear()

        def add_light(pos, dir_v, color, mult, size):
            light = er_core.er_create_light()
            er_core.er_set_light_properties(
                light,
                float(pos[0]), float(pos[1]), float(pos[2]),
                float(dir_v[0]), float(dir_v[1]), float(dir_v[2]),
                float(color[0]), float(color[1]), float(color[2]),
                float(mult), float(size[0]), float(size[1])
            )
            er_core.er_bind_light(light)
            er_core.er_tracer_add_light(self.tracer, light)
            self.lights.append(light)

        # Key Light
        add_light(key_pos, key_dir, key_color, key_mult, key_size)
        # Fill Light
        add_light(fill_pos, fill_dir, fill_color, fill_mult, fill_size)
        # Rim Light
        add_light(rim_pos, rim_dir, rim_color, rim_mult, rim_size)

    def set_camera(self, pos, target, up, fov, clip_near, clip_far, exposure, gamma):
        er_core.er_set_camera(self.tracer, 
            float(pos[0]), float(pos[1]), float(pos[2]),
            float(target[0]), float(target[1]), float(target[2]),
            float(up[0]), float(up[1]), float(up[2]),
            float(fov), float(clip_near), float(clip_far),
            float(exposure), float(gamma))

    def set_resolution(self, w, h):
        er_core.er_set_tracer_resolution(self.tracer, int(w), int(h))

    def update_opacity_tf(self, points):
        er_core.er_clear_opacity_tf(self.tracer)
        for val, op in points:
            er_core.er_add_opacity_node(self.tracer, float(val), float(op))

    def update_diffuse_tf(self, points):
        er_core.er_clear_diffuse_tf(self.tracer)
        for val, r, g, b in points:
            er_core.er_add_diffuse_node(self.tracer, float(val), float(r), float(g), float(b))

    def bind_tracer(self):
        er_core.er_bind_tracer(self.tracer)
        
    def get_tracer_id(self):
        return er_core.er_get_tracer_id(self.tracer)

    def reset_accumulation(self):
        er_core.er_reset_accumulation(self.tracer)
        
    def render_estimate(self, tracer_id):
        er_core.er_render_estimate(tracer_id)

    def get_estimate(self, tracer_id, buffer_ptr):
        er_core.er_get_estimate(tracer_id, buffer_ptr)
    def bind_volume_data(self, dim, spacing, data_ptr):
        er_core.er_bind_volume_data(
            self.volume,
            int(dim[0]), int(dim[1]), int(dim[2]),
            float(spacing[0]), float(spacing[1]), float(spacing[2]),
            data_ptr
        )
        er_core.er_bind_volume(self.volume)

import vtk
from PySide6 import QtCore, QtWidgets
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor

def qt_message_handler(mode, context, message):
    if "invalid metadata" in message.lower() or "unexpected metadata" in message.lower():
        return
    sys.stderr.write(f"{message}\n")

QtCore.qInstallMessageHandler(qt_message_handler)

from PyCt6 import (
    CButton, CLabel, CLineEdit, CTextEdit, CComboBox, CSlider, CFrame,
    set_appearance_mode, set_color_theme
)
from PySide6.QtGui import QPainter, QColor, QIcon

import SimpleITK as sitk
import tempfile
from vtkmodules.util import numpy_support
import numpy as np

from segmentation.pipeline import SegmentationPipeline
from segmentation.visualizer import SegmentationVisualizer
from segmentation.config import (
    DEFAULT_CLOSING_KERNEL,
    DEFAULT_HU_WINDOW,
    DEFAULT_MIN_COMPONENT_SIZE,
    DEFAULT_NUM_CLICKS,
    DEFAULT_TARGET_SPACING,
    DEFAULT_THRESHOLD,
)

HAS_MC_RDENOISER = False

def _compute_frangi_from_hessian(Hxx, Hyy, Hzz, Hxy, Hxz, Hyz,
                                  alpha=1.0, beta=0.5, gamma=10.0, dark_ridges=True):
    shape = Hxx.shape
    n_total = Hxx.size
    H = np.empty((n_total, 3, 3), dtype=np.float32)
    H[:, 0, 0] = Hxx.ravel()
    H[:, 0, 1] = Hxy.ravel()
    H[:, 0, 2] = Hxz.ravel()
    H[:, 1, 0] = Hxy.ravel()
    H[:, 1, 1] = Hyy.ravel()
    H[:, 1, 2] = Hyz.ravel()
    H[:, 2, 0] = Hxz.ravel()
    H[:, 2, 1] = Hyz.ravel()
    H[:, 2, 2] = Hzz.ravel()
    eigvals = np.linalg.eigvalsh(H)
    if dark_ridges:
        eigvals = -eigvals
    lam1 = eigvals[:, 0]
    lam2 = eigvals[:, 1]
    lam3 = eigvals[:, 2]

    v = np.zeros(n_total, dtype=np.float32)
    mask = (lam2 < 0) | (lam3 < 0)
    idx = np.where(mask)[0]

    if len(idx) == 0:
        return np.zeros(shape, dtype=np.float32)

    Ra = np.abs(lam2[idx]) / np.maximum(1e-12, np.abs(lam3[idx]))
    Rb = np.abs(lam1[idx]) / np.maximum(1e-12, np.sqrt(np.abs(lam2[idx] * lam3[idx])))
    S = np.sqrt(lam1[idx]**2 + lam2[idx]**2 + lam3[idx]**2)

    vesselness = np.exp(-Ra * Ra / (2.0 * alpha * alpha)) * \
                 (1.0 - np.exp(-Rb * Rb / (2.0 * beta * beta))) * \
                 (1.0 - np.exp(-S * S / (2.0 * gamma * gamma)))

    v[idx] = vesselness
    return v.reshape(shape).astype(np.float32)

def _build_2d_tf_lut(lut_size: int = 256, gm_max: float = 200.0) -> np.ndarray:
    hu_min, hu_max = -1000.0, 3000.0
    lut = np.zeros((lut_size, lut_size), dtype=np.float32)
    hu_grid, gm_grid = np.meshgrid(
        np.linspace(hu_min, hu_max, lut_size),
        np.linspace(0, gm_max, lut_size)
    )
    def gauss(hu_c, gm_c, hu_s, gm_s):
        return np.exp(-((hu_grid - hu_c) / hu_s) ** 2 - ((gm_grid - gm_c) / gm_s) ** 2)
    gm_scale = gm_max / 200.0
    lut += gauss(800, 100 * gm_scale, 400, 80 * gm_scale) * 1.00
    lut += gauss(700, 20 * gm_scale, 500, 30 * gm_scale) * 0.60
    lut += gauss(50, 10 * gm_scale, 150, 25 * gm_scale) * 0.80
    lut += gauss(300, 50 * gm_scale, 200, 60 * gm_scale) * 0.70
    lut += gauss(100, 30 * gm_scale, 120, 40 * gm_scale) * 0.50
    return np.clip(lut, 0.0, 1.0)

def _build_2d_tf_lut_bone_mono(lut_size: int = 256, gm_max: float = 200.0) -> np.ndarray:
    hu_min, hu_max = -1000.0, 3000.0
    lut = np.zeros((lut_size, lut_size), dtype=np.float32)
    hu_grid, gm_grid = np.meshgrid(
        np.linspace(hu_min, hu_max, lut_size),
        np.linspace(0, gm_max, lut_size)
    )
    def gauss(hu_c, gm_c, hu_s, gm_s):
        return np.exp(-((hu_grid - hu_c) / hu_s) ** 2 - ((gm_grid - gm_c) / gm_s) ** 2)
    gm_scale = gm_max / 200.0
    lut += gauss(900, 120 * gm_scale, 350, 90 * gm_scale) * 1.00
    lut += gauss(750, 15 * gm_scale, 450, 25 * gm_scale) * 0.65
    lut += gauss(30, 8 * gm_scale, 140, 20 * gm_scale) * 0.85
    lut += gauss(280, 45 * gm_scale, 180, 55 * gm_scale) * 0.75
    lut += gauss(120, 28 * gm_scale, 110, 35 * gm_scale) * 0.55
    return np.clip(lut, 0.0, 1.0)

def build_reader(dicom_path: str, denoise_method: str = "gaussian", use_clahe: bool = False, use_frangi: bool = False, use_distance_field: bool = False, use_2d_tf: bool = False, use_2d_tf_bone: bool = False, vram_threshold_gb: float = 10.0, cpu_render: bool = False) -> Tuple[vtk.vtkImageData, str]:
    if os.path.isdir(dicom_path):
        reader = sitk.ImageSeriesReader()
        dicom_names = reader.GetGDCMSeriesFileNames(dicom_path)
        if not dicom_names:
            raise RuntimeError("在目录下未找到 DICOM 序列。")
        reader.SetFileNames(dicom_names)
        image = reader.Execute()
    else:
        image = sitk.ReadImage(dicom_path)

    # 如果是 4D 数据，提取第一个时间阶段的 3D 数据
    if image.GetDimension() > 3:
        if image.GetDimension() == 4:
            image = image[:, :, :, 0]

    # [显存保护机制] 估算显存占用并自动下采样
    size = image.GetSize()
    num_voxels = 1
    for s in size:
        num_voxels *= s

    # 估算显存：2 bytes/voxel * 2.5倍 VTK底层占用膨胀系数
    estimated_vram_gb = (num_voxels * 2 * 2.5) / (1024**3)
    downsample_msg = ""
    need_downsample = estimated_vram_gb > vram_threshold_gb
    if cpu_render:
        print(f"[CPU Render] 跳过下采样，保留全分辨率: 体积 {num_voxels/1e6:.1f}M 体素, 预估 VRAM {estimated_vram_gb:.1f}GB (CPU 端使用系统 RAM)")
        need_downsample = False
    if (use_2d_tf or use_2d_tf_bone) and num_voxels > 200_000_000:
        print(f"[2D TF / Bone Mono] 体积 {num_voxels/1e6:.0f}M > 200M 体素, 触发自动下采样 (1024³→512³)")
        need_downsample = True
    if num_voxels > 500_000_000 and not need_downsample and not cpu_render:
        print(f"[Volume Guard] 体积 {num_voxels/1e6:.0f}M > 500M 体素, GPU 可能无法分配 3D 纹理, 触发下采样")
        need_downsample = True
    if need_downsample:
        msg1 = f"[Memory Protect] Estimated VRAM {estimated_vram_gb:.1f}GB exceeds {vram_threshold_gb:.0f}GB limit, auto-downsampling..."
        print(msg1)
        downsample_msg += msg1 + "\n"
        max_dim = max(size[0], size[1])
        target = 1024 if max_dim >= 2048 else 512
        factor = max(size[0] / target, size[1] / target)
        if factor > 1.0:
            new_size = list(size)
            new_spacing = list(image.GetSpacing())
            new_size[0] = max(target, int(size[0] / factor))
            new_size[1] = max(target, int(size[1] / factor))
            if len(size) >= 3:
                new_size[2] = max(1, int(size[2] / factor))

            for i in range(len(new_size)):
                new_spacing[i] = image.GetSpacing()[i] * (size[i] / new_size[i])

            resampler = sitk.ResampleImageFilter()
            resampler.SetSize(new_size)
            resampler.SetOutputSpacing(new_spacing)
            resampler.SetOutputOrigin(image.GetOrigin())
            resampler.SetOutputDirection(image.GetDirection())
            resampler.SetInterpolator(sitk.sitkLinear)
            resampler.SetDefaultPixelValue(-1000)
            image = resampler.Execute(image)
            msg2 = f"[Memory Protect] Downsample completed: {size} -> {image.GetSize()}"
            print(msg2)
            downsample_msg += msg2

    # 保证 2D/3D 数据提取为 3D 数组(ZYX) 传入 VTK
    nda = sitk.GetArrayFromImage(image)
    while nda.ndim > 3:
        nda = nda[0]
    if nda.ndim == 2:
        nda = nda[np.newaxis, ...]
    nda = np.ascontiguousarray(nda.astype(np.int16, copy=False))

    import scipy.ndimage as ndimage
    if denoise_method == "nlm":
        try:
            from skimage.restoration import denoise_nl_means
            print("应用 3D Non-Local Means 降噪 (patch=5, distance=7) 保留微通道边缘...")
            try:
                from PySide6.QtWidgets import QApplication
                QApplication.processEvents()
            except Exception:
                pass
            est_sigma = max(1.0, float(np.std(nda)) * 0.4)
            nda_f32 = nda.astype(np.float32)
            n_vox = int(nda_f32.size)
            if n_vox > 80_000_000:
                import time
                nz = nda_f32.shape[0]
                chunk_sz = int(max(8, min(64, vram_threshold_gb * 4)))
                if n_vox > 200_000_000:
                    chunk_sz = max(8, chunk_sz // 2)
                total_chunks = (nz + chunk_sz - 1) // chunk_sz
                nlm_patch = 3
                nlm_dist = 5
                nlm_pad = nlm_patch + nlm_dist
                print(f"  NLM 体积 {n_vox/1e6:.1f}M > 80M 体素, VRAM={vram_threshold_gb:.0f}GB→chunk={chunk_sz}, patch={nlm_patch}, dist={nlm_dist}, {total_chunks} chunks")
                t_start = time.time()
                for ci, z0 in enumerate(range(0, nz, chunk_sz)):
                    z1 = min(z0 + chunk_sz + nlm_pad, nz)
                    chunk = nda_f32[z0:z1, :, :].copy()
                    pad_trim = 0 if z0 == 0 else min(nlm_pad, z1 - z0)
                    denoised = denoise_nl_means(chunk, patch_size=nlm_patch, patch_distance=nlm_dist,
                                                h=est_sigma, fast_mode=True, preserve_range=True,
                                                channel_axis=None)
                    write_sz = min(chunk_sz, nz - z0)
                    end_trim = min(pad_trim + write_sz, denoised.shape[0])
                    nda[z0:z0 + write_sz] = denoised[pad_trim:end_trim, :, :].astype(np.int16)
                    elapsed = time.time() - t_start
                    eta = elapsed / (ci + 1) * (total_chunks - ci - 1)
                    print(f"  NLM chunk {ci+1}/{total_chunks} [{z0}:{z0+write_sz}] 耗时 {elapsed:.0f}s, ETA {eta:.0f}s")
                    try:
                        from PySide6.QtWidgets import QApplication
                        QApplication.processEvents()
                    except Exception:
                        pass
                nda = nda.astype(np.int16)
                print(f"  NLM 完成, 总耗时 {time.time()-t_start:.0f}s")
                del nda_f32
            else:
                nda_f32 = denoise_nl_means(nda_f32, patch_size=5, patch_distance=7,
                                           h=est_sigma, fast_mode=True, preserve_range=True,
                                           channel_axis=None).astype(np.int16)
                nda = nda_f32
                del nda_f32
        except Exception as e:
            print(f"NLM 降噪不可用 ({e})，回退至高斯滤波。")
            nda = ndimage.gaussian_filter(nda, sigma=0.4)
    else:
        print("应用 3D 高斯平滑滤波 (Sigma=0.4) 保留更多表面细节...")
        nda = ndimage.gaussian_filter(nda, sigma=0.4)

    if use_clahe:
        try:
            from skimage import exposure
            print("应用 3D CLAHE 局部对比度增强 (kernel=64, clip=0.02)...")
            nda_f32 = nda.astype(np.float32)
            nda_min, nda_max = nda_f32.min(), nda_f32.max()
            nda_norm = (nda_f32 - nda_min) / max(1e-6, nda_max - nda_min)
            nda_eq = np.empty_like(nda_norm)
            for z in range(nda_norm.shape[0]):
                nda_eq[z] = exposure.equalize_adapthist(nda_norm[z], kernel_size=64, clip_limit=0.02)
            nda = (nda_eq * (nda_max - nda_min) + nda_min).astype(np.int16)
            print("CLAHE 增强完成。")
        except Exception as e:
            print(f"CLAHE 增强失败 ({e})，继续使用原始数据。")

    if use_frangi:
        try:
            from skimage.filters import frangi as frangi_cpu
            use_gpu = False
            gpu_fail_reason = ""
            try:
                import cupy as cp
                from cupyx.scipy.ndimage import gaussian_filter as cp_gaussian_filter
                cp_test = cp.array([1.0])
                del cp_test
                gpu_mem = cp.cuda.runtime.memGetInfo()
                gpu_mem_gb = gpu_mem[0] / (1024**3)
                use_gpu = True
                print(f"CuPy GPU 可用: 空闲显存 {gpu_mem_gb:.1f} GB")
            except ImportError as e:
                gpu_fail_reason = f"CuPy 未安装或不可导入: {e}"
            except Exception as e:
                gpu_fail_reason = f"CuPy 初始化失败: {e}"

            if not use_gpu:
                print(f"GPU 不可用 ({gpu_fail_reason})，使用 CPU 计算 Frangi...")

            spacing = image.GetSpacing()
            min_sp = float(min(spacing))
            if min_sp <= 0.001:
                min_sp = 1.0
            sigmas_mm = [0.2, 0.3, 0.5, 0.8]
            sigmas_px = [s / min_sp for s in sigmas_mm]
            sigmas_px = [s for s in sigmas_px if s >= 0.6]
            if not sigmas_px:
                sigmas_px = [0.6]

            print(f"计算 3D Frangi Vesselness (dark tube, sigma_mm={sigmas_mm}, sigma_px={[f'{s:.1f}' for s in sigmas_px]}, GPU={use_gpu}) ...")

            if use_gpu:
                nda_f32 = nda.astype(np.float32)
                orig_shape = nda_f32.shape
                n_vox = orig_shape[0] * orig_shape[1] * orig_shape[2]
                vesselness_cpu = np.zeros(orig_shape, dtype=np.float32)

                if n_vox > 80_000_000:
                    chunk_size = max(16, orig_shape[0] // 6)
                else:
                    chunk_size = orig_shape[0]

                for sigma_px in sigmas_px:
                    print(f"  Frangi σ={sigma_px:.1f}px (GPU) ...")

                    for z_start in range(0, orig_shape[0], chunk_size):
                        z_end = min(z_start + chunk_size, orig_shape[0])
                        pad_before = int(sigma_px * 4)
                        pad_after = int(sigma_px * 4)
                        z0 = max(0, z_start - pad_before)
                        z1 = min(orig_shape[0], z_end + pad_after)

                        chunk = cp.asarray(nda_f32[z0:z1, :, :].copy(), dtype=cp.float32)
                        chunk_sz = z1 - z0
                        actual_start = z_start - z0
                        actual_end = z_end - z0

                        smoothed = cp_gaussian_filter(chunk, sigma_px, mode='reflect')
                        Dxx = cp_gaussian_filter(smoothed, sigma_px, order=(2, 0, 0), mode='reflect')
                        Dyy = cp_gaussian_filter(smoothed, sigma_px, order=(0, 2, 0), mode='reflect')
                        Dzz = cp_gaussian_filter(smoothed, sigma_px, order=(0, 0, 2), mode='reflect')
                        Dxy = cp_gaussian_filter(smoothed, sigma_px, order=(1, 1, 0), mode='reflect')
                        Dxz = cp_gaussian_filter(smoothed, sigma_px, order=(1, 0, 1), mode='reflect')
                        Dyz = cp_gaussian_filter(smoothed, sigma_px, order=(0, 1, 1), mode='reflect')

                        Hxx = cp.asnumpy(Dxx[actual_start:actual_end, :, :])
                        Hyy = cp.asnumpy(Dyy[actual_start:actual_end, :, :])
                        Hzz = cp.asnumpy(Dzz[actual_start:actual_end, :, :])
                        Hxy = cp.asnumpy(Dxy[actual_start:actual_end, :, :])
                        Hxz = cp.asnumpy(Dxz[actual_start:actual_end, :, :])
                        Hyz = cp.asnumpy(Dyz[actual_start:actual_end, :, :])

                        del smoothed, Dxx, Dyy, Dzz, Dxy, Dxz, Dyz, chunk
                        cp.get_default_memory_pool().free_all_blocks()

                        v = _compute_frangi_from_hessian(
                            Hxx, Hyy, Hzz, Hxy, Hxz, Hyz,
                            alpha=1.0, beta=0.5, gamma=10.0, dark_ridges=True
                        )
                        vesselness_cpu[z_start:z_end, :, :] = np.maximum(
                            vesselness_cpu[z_start:z_end, :, :], v
                        )
                        try:
                            from PySide6.QtWidgets import QApplication
                            QApplication.processEvents()
                        except Exception:
                            pass
                vesselness = vesselness_cpu.astype(np.float32)
            else:
                nda_f32 = nda.astype(np.float32)
                vox_count = nda_f32.size
                est_mem_gb = vox_count * 4 * 3 / (1024**3)
                print(f"  Frangi CPU 模式: {sigmas_px} 尺度, 体积 {vox_count/1e6:.1f}M 体素")
                print(f"  预估 CPU 内存占用 ~{est_mem_gb:.1f} GB (FP32)")
                if vox_count > 80_000_000:
                    print(f"  体积 > 80M 体素, 使用 Z轴分块 Frangi (chunk=64 slices, 96GB RAM safe)...")
                    import time
                    vesselness = np.zeros(nda_f32.shape, dtype=np.float32)
                    nz = nda_f32.shape[0]
                    chunk_sz = 64
                    for z0 in range(0, nz, chunk_sz):
                        z1 = min(z0 + chunk_sz + 16, nz)
                        chunk = nda_f32[z0:z1, :, :].copy()
                        pad = min(8, z1 - z0)
                        for i, sigma_px in enumerate(sigmas_px):
                            t0 = time.time()
                            v = frangi_cpu(chunk.astype(np.float64), sigmas=[sigma_px],
                                           alpha=1.0, beta=0.5, gamma=10.0,
                                           black_ridges=True, mode='reflect')
                            write_sz = min(chunk_sz, nz - z0)
                            v_slice = v[pad:pad + write_sz, :, :].astype(np.float32)
                            vesselness[z0:z0 + write_sz, :, :] = np.maximum(
                                vesselness[z0:z0 + write_sz, :, :], v_slice)
                            print(f"  Frangi σ={sigma_px:.1f}px Z[{z0}:{z0+write_sz}] 完成, {time.time()-t0:.1f}s")
                        try:
                            from PySide6.QtWidgets import QApplication
                            QApplication.processEvents()
                        except Exception:
                            pass
                else:
                    vesselness = np.zeros(nda_f32.shape, dtype=np.float32)
                    for i, sigma_px in enumerate(sigmas_px):
                        print(f"  Frangi σ={sigma_px:.1f}px ({i+1}/{len(sigmas_px)}) (CPU) ...")
                        try:
                            from PySide6.QtWidgets import QApplication
                            QApplication.processEvents()
                        except Exception:
                            pass
                        import time
                        t0 = time.time()
                        v = frangi_cpu(nda_f32.astype(np.float64), sigmas=[sigma_px],
                                       alpha=1.0, beta=0.5, gamma=10.0,
                                       black_ridges=True, mode='reflect')
                        vesselness = np.maximum(vesselness, v.astype(np.float32))
                        print(f"    完成, 耗时 {time.time()-t0:.1f}s")

            print(f"Frangi 完成: vesselness range=[{vesselness.min():.4f}, {vesselness.max():.4f}]")
            boost_offset = np.int16(1200)
            vessel_mask = vesselness > 0.12
            nda_mod = nda.astype(np.int32)
            nda_mod[vessel_mask] += boost_offset
            nda = np.clip(nda_mod, -1000, 3000).astype(np.int16)
            n_voxels = int(vessel_mask.sum())
            print(f"Frangi HU 偏移完成: {n_voxels} 体素标记为微通道候选 (boost +{boost_offset} HU)")
        except Exception as e:
            import traceback
            print(f"Frangi 计算失败 ({e}):")
            traceback.print_exc()

    if use_distance_field:
        try:
            from scipy.ndimage import distance_transform_edt
            import time
            spacing = image.GetSpacing()
            sx, sy, sz = float(spacing[0]), float(spacing[1]), float(spacing[2])
            dist_decay_start_mm = 1.0
            dist_decay_end_mm = 4.0
            bone_threshold = 300
            print(f"计算距离场骨膜聚合 (骨阈值>{bone_threshold}HU, 衰减 {dist_decay_start_mm}-{dist_decay_end_mm}mm)...")
            t0 = time.time()
            bone_mask = (nda > bone_threshold).astype(np.uint8)
            dist_vx = distance_transform_edt(1 - bone_mask, sampling=(sx, sy, sz))
            decay = np.clip((dist_vx - dist_decay_start_mm) / (dist_decay_end_mm - dist_decay_start_mm), 0.0, 1.0)
            nda_f32 = nda.astype(np.float32)
            air_val = np.float32(-1000)
            soft_mask = nda_f32 < bone_threshold
            nda_f32[soft_mask] = nda_f32[soft_mask] * (1.0 - decay[soft_mask]) + air_val * decay[soft_mask]
            nda = np.clip(nda_f32, -1000, 3000).astype(np.int16)
            kept_vox = int((decay < 0.99).sum())
            print(f"  距离场完成, {time.time()-t0:.1f}s. 骨膜保留体素 {kept_vox/1e6:.1f}M (距离<{dist_decay_end_mm}mm)")
            try:
                from PySide6.QtWidgets import QApplication
                QApplication.processEvents()
            except Exception:
                pass
        except Exception as e:
            import traceback
            print(f"距离场计算失败 ({e}):")
            traceback.print_exc()

    if use_2d_tf:
        try:
            from scipy.ndimage import sobel
            import time, sys
            lut_mode = "Bone Monochrome" if use_2d_tf_bone else "Kniss 2001"
            n_vox = nda.size
            if n_vox > 200_000_000:
                print(f"  2D TF 预处理: 体积 {n_vox/1e6:.0f}M > 200M 体素, 预计内存消耗 ~{n_vox*4*4/1e9:.1f}GB, 耗时数分钟...")
                sys.stdout.flush()
            print(f"计算 2D TF (HU × Gradient Magnitude) {lut_mode} 风格预处理...")
            sys.stdout.flush()
            t0 = time.time()
            nda_f32 = nda.astype(np.float32)
            gx = sobel(nda_f32, axis=0); sys.stdout.flush()
            gy = sobel(nda_f32, axis=1); sys.stdout.flush()
            gz = sobel(nda_f32, axis=2); sys.stdout.flush()
            gm = np.sqrt(gx**2 + gy**2 + gz**2)
            del gx, gy, gz
            print(f"  梯度幅值完成 ({time.time()-t0:.1f}s), GM range=[{gm.min():.1f}, {gm.max():.1f}]")
            sys.stdout.flush()
            if gm.size > 50_000_000:
                sample = np.random.choice(gm.ravel(), min(500_000, gm.size), replace=False)
                gm_max_lut = max(200.0, float(np.percentile(sample, 95)))
            else:
                gm_max_lut = max(200.0, float(np.percentile(gm, 95)))
            print(f"  gm_max_lut adjusted to P95 = {gm_max_lut:.0f}")
            sys.stdout.flush()
            lut_2d = _build_2d_tf_lut_bone_mono(256, gm_max_lut) if use_2d_tf_bone else _build_2d_tf_lut(256, gm_max_lut)
            hu_min, hu_max = -1000.0, 3000.0
            hu_idx = np.clip(((nda_f32 - hu_min) / (hu_max - hu_min) * 255).astype(np.int32), 0, 255)
            gm_idx = np.clip(((gm / gm_max_lut) * 255).astype(np.int32), 0, 255)
            alpha_2d = lut_2d[gm_idx, hu_idx]
            print(f"  2D TF 查询完成 ({time.time()-t0:.1f}s), 可见体素>0.05={(alpha_2d>0.05).sum()/1e6:.1f}M")
            sys.stdout.flush()
            nda_mod = nda.astype(np.float32)
            fade_mask = alpha_2d < 0.05
            nda_mod[fade_mask] = -1000
            fade_smooth = np.clip((0.10 - alpha_2d) / 0.10, 0, 1)
            mid_mask = (alpha_2d >= 0.05) & (alpha_2d < 0.15)
            nda_mod[mid_mask] = nda_mod[mid_mask] * (1 - fade_smooth[mid_mask]) - 1000 * fade_smooth[mid_mask]
            nda = np.clip(nda_mod, -1000, 3000).astype(np.int16)
            surv = (nda > -900).sum()
            del nda_f32, alpha_2d, nda_mod, gm, fade_mask, mid_mask, fade_smooth
            print(f"  2D TF 体积重映射完成, 总耗时 {time.time()-t0:.1f}s")
            print(f"  Surviving voxels > -900 HU: {surv/1e6:.1f}M / {nda.size/1e6:.1f}M ({surv/nda.size*100:.1f}%)")
            try:
                import matplotlib
                matplotlib.use('Agg')
                import matplotlib.pyplot as plt
                fig, ax = plt.subplots(figsize=(6, 5))
                im = ax.imshow(lut_2d, origin='lower', extent=[hu_min, hu_max, 0, gm_max_lut],
                               aspect='auto', cmap='gray_r')
                ax.set_xlabel('HU'); ax.set_ylabel('Gradient Magnitude')
                ax.set_title('2D TF LUT (Kniss 2001)')
                plt.colorbar(im, label='Opacity')
                lut_path = os.path.join(tempfile.gettempdir(), 'ssd_vr_2dtf_lut.png')
                fig.savefig(lut_path, dpi=100, bbox_inches='tight')
                plt.close(fig)
                print(f"  2D TF LUT 可视化保存至 {lut_path}")
            except Exception:
                pass
            try:
                from PySide6.QtWidgets import QApplication
                QApplication.processEvents()
            except Exception:
                pass
        except Exception as e:
            import traceback
            print(f"2D TF 计算失败 ({e}):")
            traceback.print_exc()

    vtk_data = numpy_support.numpy_to_vtk(
        num_array=nda.ravel(order="C"), deep=True, array_type=vtk.VTK_SHORT     
    )

    final_size = list(image.GetSize())
    spacing = list(image.GetSpacing())
    origin = list(image.GetOrigin())
    if len(final_size) > 3:
        final_size = final_size[:3]
        spacing = spacing[:3]
        origin = origin[:3]
    elif len(final_size) == 2:
        final_size = [final_size[0], final_size[1], 1]
        spacing = [spacing[0], spacing[1], 1.0]
        origin = [origin[0], origin[1], 0.0]

    img_vtk = vtk.vtkImageData()
    img_vtk.SetDimensions(int(final_size[0]), int(final_size[1]), int(final_size[2]))
    img_vtk.SetSpacing(float(spacing[0]), float(spacing[1]), float(spacing[2])) 
    img_vtk.SetOrigin(float(origin[0]), float(origin[1]), float(origin[2]))     
    img_vtk.GetPointData().SetScalars(vtk_data)

    return img_vtk, downsample_msg


def make_opacity(points: List[Tuple[float, float]], scale: float = 1.0) -> vtk.vtkPiecewiseFunction:
    otf = vtk.vtkPiecewiseFunction()
    for x, y in points:
        otf.AddPoint(x, max(0.0, min(1.0, y * scale)))
    return otf


def make_color(points: List[Tuple[float, float, float, float]]) -> vtk.vtkColorTransferFunction:
    ctf = vtk.vtkColorTransferFunction()
    for x, r, g, b in points:
        ctf.AddRGBPoint(x, r, g, b)
    return ctf


def interp_piecewise(points: List[Tuple[float, float]], x: float) -> float:
    if not points:
        return 0.0
    if x <= points[0][0]:
        return points[0][1]
    for i in range(1, len(points)):
        x0, y0 = points[i - 1]
        x1, y1 = points[i]
        if x <= x1:
            t = 0.0 if x1 == x0 else (x - x0) / (x1 - x0)
            return y0 * (1.0 - t) + y1 * t
    return points[-1][1]


def interp_color(points: List[Tuple[float, float, float, float]], x: float) -> Tuple[float, float, float]:
    if not points:
        return 0.0, 0.0, 0.0
    if x <= points[0][0]:
        return points[0][1], points[0][2], points[0][3]
    for i in range(1, len(points)):
        x0, r0, g0, b0 = points[i - 1]
        x1, r1, g1, b1 = points[i]
        if x <= x1:
            t = 0.0 if x1 == x0 else (x - x0) / (x1 - x0)
            return (
                r0 * (1.0 - t) + r1 * t,
                g0 * (1.0 - t) + g1 * t,
                b0 * (1.0 - t) + b1 * t,
            )
    return points[-1][1], points[-1][2], points[-1][3]


class FusionController:
    def __init__(
        self,
        ssd_volume: Optional[vtk.vtkVolume],
        vr_volume: Optional[vtk.vtkVolume],
        ssd_points: List[Tuple[float, float]],
        vr_points: List[Tuple[float, float]],
        ssd_color_points: List[Tuple[float, float, float, float]],
        vr_color_points: List[Tuple[float, float, float, float]],
        fused_volume: Optional[vtk.vtkVolume] = None,
    ) -> None:
        self.ssd_volume = ssd_volume
        self.vr_volume = vr_volume
        self.fused_volume = fused_volume
        self.ssd_points = ssd_points
        self.vr_points = vr_points
        self.ssd_color_points = ssd_color_points
        self.vr_color_points = vr_color_points

    def update(self, ssd_scale: float, vr_scale: float, exposure: float = 1.0) -> None:
        if self.fused_volume is not None:
            op, col = self._build_fused_transfer(ssd_scale, vr_scale, exposure)
            prop = self.fused_volume.GetProperty()
            prop.SetScalarOpacity(op)
            prop.SetColor(col)
            return
        if self.ssd_volume is not None:
            self.ssd_volume.GetProperty().SetScalarOpacity(make_opacity(self.ssd_points, ssd_scale))
        if self.vr_volume is not None:
            self.vr_volume.GetProperty().SetScalarOpacity(make_opacity(self.vr_points, vr_scale))

    def _build_fused_transfer(
        self, ssd_scale: float, vr_scale: float, exposure: float
    ) -> Tuple[vtk.vtkPiecewiseFunction, vtk.vtkColorTransferFunction]:
        # 参考 Exposure Render：两类体材质在同一体积内融合，再做指数色调映射近似
        hu_samples = list(range(-1000, 3001, 20))
        otf = vtk.vtkPiecewiseFunction()
        ctf = vtk.vtkColorTransferFunction()
        # tonemap.cuh: c_out = 1 - exp(-c_in * Exposure)
        for hu in hu_samples:
            a_ssd = max(0.0, min(1.0, interp_piecewise(self.ssd_points, hu) * ssd_scale))
            a_vr = max(0.0, min(1.0, interp_piecewise(self.vr_points, hu) * vr_scale))
            a_mix = 1.0 - (1.0 - a_ssd) * (1.0 - a_vr)
            r1, g1, b1 = interp_color(self.ssd_color_points, hu)
            r2, g2, b2 = interp_color(self.vr_color_points, hu)
            w = a_ssd + a_vr
            if w > 1e-6:
                r = (r1 * a_ssd + r2 * a_vr) / w
                g = (g1 * a_ssd + g2 * a_vr) / w
                b = (b1 * a_ssd + b2 * a_vr) / w
            else:
                r, g, b = r2, g2, b2
            
            # Apply exposure multiplier
            r = 1.0 - np.exp(-r * exposure)
            g = 1.0 - np.exp(-g * exposure)
            b = 1.0 - np.exp(-b * exposure)
            otf.AddPoint(float(hu), float(a_mix))
            ctf.AddRGBPoint(float(hu), float(r), float(g), float(b))
        return otf, ctf


class RangeSlider(QtWidgets.QWidget):
    valueChanged = QtCore.Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.minimum = -1000
        self.maximum = 3000
        self._lower = 300
        self._upper = 1500
        self._handle_radius = 8
        self._active_handle = None
        self._drag_offset = 0
        self.setFixedHeight(30)
        
    def setRange(self, min_val, max_val):
        self.minimum = min_val
        self.maximum = max_val
        self.update()
        
    def setValues(self, lower, upper):
        self._lower = max(self.minimum, min(lower, self.maximum))
        self._upper = max(self.minimum, min(upper, self.maximum))
        self.update()
        self.valueChanged.emit(int(self._lower), int(self._upper))
        
    def blockSignals(self, b):
        return super().blockSignals(b)
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        w = self.width()
        h = self.height()
        r = self._handle_radius
        
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QColor(60, 24, 34))
        painter.drawRoundedRect(r, h//2 - 2, w - 2*r, 4, 2, 2)
        
        lx = self._val_to_pos(self._lower)
        ux = self._val_to_pos(self._upper)
        
        painter.setBrush(QColor(140, 48, 64))
        painter.drawRoundedRect(QtCore.QRectF(lx, h//2 - 2, ux - lx, 4), 2, 2)
        
        painter.setPen(QColor(130, 90, 100))
        painter.setBrush(QColor(215, 185, 194))
        painter.drawEllipse(QtCore.QPointF(lx, h//2), r, r)
        painter.drawEllipse(QtCore.QPointF(ux, h//2), r, r)
        
    def _val_to_pos(self, val):
        w = self.width() - 2 * self._handle_radius
        return self._handle_radius + w * (val - self.minimum) / (self.maximum - self.minimum)
        
    def _pos_to_val(self, x):
        w = self.width() - 2 * self._handle_radius
        val = self.minimum + (x - self._handle_radius) / w * (self.maximum - self.minimum)
        return max(self.minimum, min(self.maximum, val))
        
    def mousePressEvent(self, event):
        x = event.pos().x()
        lx = self._val_to_pos(self._lower)
        ux = self._val_to_pos(self._upper)
        
        if abs(x - lx) < self._handle_radius * 2:
            self._active_handle = 'lower'
        elif abs(x - ux) < self._handle_radius * 2:
            self._active_handle = 'upper'
        elif lx < x < ux:
            self._active_handle = 'center'
            self._drag_offset = x
            self._drag_lower_start = self._lower
            self._drag_upper_start = self._upper
        else:
            self._active_handle = None

    def mouseMoveEvent(self, event):
        if not self._active_handle:
            return
        x = event.pos().x()
        val = self._pos_to_val(x)
        
        if self._active_handle == 'lower':
            self._lower = min(val, self._upper - 1)
        elif self._active_handle == 'upper':
            self._upper = max(val, self._lower + 1)
        elif self._active_handle == 'center':
            delta_val = self._pos_to_val(x) - self._pos_to_val(self._drag_offset)
            new_lower = self._drag_lower_start + delta_val
            new_upper = self._drag_upper_start + delta_val
            
            if new_lower < self.minimum:
                diff = self.minimum - new_lower
                new_lower += diff
                new_upper += diff
            elif new_upper > self.maximum:
                diff = new_upper - self.maximum
                new_lower -= diff
                new_upper -= diff
                
            self._lower = new_lower
            self._upper = new_upper
            
        self.update()
        self.valueChanged.emit(int(self._lower), int(self._upper))
        
    def mouseReleaseEvent(self, event):
        self._active_handle = None


class ViewerWindow(QtWidgets.QMainWindow):
    def __init__(self, initial_input: Optional[str] = None) -> None:
        super().__init__()
        self.setWindowTitle("SSD+VR Fusion Viewer")
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.jpg")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.resize(1520, 920)

        self.initial_input = initial_input or ""
        self.controller = None  # type: Optional[FusionController]
        self.current_ssd_volume = None  # type: Optional[vtk.vtkVolume]
        self.current_vr_volume = None  # type: Optional[vtk.vtkVolume]
        self.render_mode = "stable"  # stable | hd_surface | cinematic | nature_channels | spectral | exposure_render
        self.mc_quality = 0.60  # 0-1, 越高路径追踪采样越密
        self.scatter_blend = 0.65  # 0-1, 混合散射强度
        self.scatter_g = 0.80  # HG 各向异性参数
        self.er_exposure = 1.50  # Exposure Render 风格曝光参数
        self.cr_denoise = 0.00   # CR 降噪控制 (0-1)
        # 预处理选项
        self.denoise_method = "gaussian"  # gaussian | nlm
        self.use_clahe = False
        self.use_frangi = False
        self.use_distance_field = False
        self.use_2d_tf = False
        self.use_2d_tf_bone = False
        self.cpu_render = False
        self.vram_threshold_gb = 10  # 用户可调显存阈值
        # 对齐 Exposure Render 的 Traversal 参数
        self.step_factor_primary = 0.10
        self.step_factor_shadow = 0.10
        # 更保守的默认显存预算，降低 nvoglv64.dll 驱动崩溃概率
        self.total_gpu_budget_bytes = 3 * 1024 * 1024 * 1024
        self.er_wrapper = None
        self.er_image_actor = None
        self.er_image_data = None
        # We don't use repeating timer anymore to avoid freezing the UI
        self.er_buffer = None
        self.last_cam_params = None
        self.last_tf_params = None

        self.seg_pipeline = None
        self.seg_visualizer = None
        self.seg_result = None
        self.original_sitk_image = None
        self.seg_renderer = None
        self.right_volume = None
        self.right_producer = None
        self.right_mapper = None
        # K-edge material rendering
        self.kedge_renderer = None
        self.kedge_loaded = False
        self.kedge_materials = {}  # {name: vtkVolume}
        self.kedge_mat_names = ["iodine", "gadolinium", "gold", "bismuth"]
        self.kedge_mat_labels = ["Iodine (碘,33.2keV)", "Gadolinium (钆,50.2keV)",
                                  "Gold (金,80.7keV)", "Bismuth (铋,90.5keV)"]
        self.kedge_mat_colors = [
            (0.90, 0.55, 0.20),   # I: warm orange
            (0.15, 0.70, 0.35),   # Gd: emerald green
            (0.95, 0.85, 0.20),   # Au: golden yellow
            (0.70, 0.30, 0.85),   # Bi: purple
        ]

        self.slicer_presets = {}
        self._load_slicer_presets()

    def _load_slicer_presets(self):
        import xml.etree.ElementTree as ET
        preset_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "presets.xml")
        if not os.path.exists(preset_file):
            print(f"Warning: Slicer preset file {preset_file} not found.")
            return
            
        try:
            tree = ET.parse(preset_file)
            root = tree.getroot()
            for vp in root.findall('VolumeProperty'):
                name = vp.get('name')
                if not name:
                    continue
                
                # Parse scalarOpacity
                so_str = vp.get('scalarOpacity', '')
                so_parts = so_str.split()
                if len(so_parts) > 0:
                    num_pts = int(so_parts[0])
                    opacity_pts = []
                    idx = 1
                    for _ in range(num_pts):
                        if idx + 1 < len(so_parts):
                            val = float(so_parts[idx])
                            op = float(so_parts[idx+1])
                            opacity_pts.append((val, op))
                            idx += 2
                else:
                    opacity_pts = []
                
                # Parse colorTransfer
                ct_str = vp.get('colorTransfer', '')
                ct_parts = ct_str.split()
                if len(ct_parts) > 0:
                    num_pts = int(ct_parts[0])
                    color_pts = []
                    idx = 1
                    for _ in range(num_pts):
                        if idx + 3 < len(ct_parts):
                            val = float(ct_parts[idx])
                            r = float(ct_parts[idx+1])
                            g = float(ct_parts[idx+2])
                            b = float(ct_parts[idx+3])
                            color_pts.append((val, r, g, b))
                            idx += 4
                else:
                    color_pts = []
                    
                ambient = float(vp.get('ambient', 0.1))
                diffuse = float(vp.get('diffuse', 0.9))
                specular = float(vp.get('specular', 0.2))
                specularPower = float(vp.get('specularPower', 10.0))
                
                self.slicer_presets[name] = {
                    'opacity': opacity_pts,
                    'color': color_pts,
                    'ambient': ambient,
                    'diffuse': diffuse,
                    'specular': specular,
                    'specularPower': specularPower
                }
        except Exception as e:
            print(f"Error parsing presets.xml: {e}")

        # Class A (SSD Layer): 胸骨外壳（稳定模式）
        self.ssd_opacity_points_stable = [
            (-1000, 0.00),
            (320, 0.00),
            (420, 0.01),
            (560, 0.10),
            (760, 0.52),
            (980, 0.86),
            (1300, 1.00),
            (3000, 1.00),
        ]
        # Class A (SSD Layer): 胸骨外壳（高清骨表模式：更高阈值、更陡峭）
        self.ssd_opacity_points_hd = [
            (-1000, 0.00),
            (380, 0.00),
            (520, 0.01),
            (700, 0.18),
            (900, 0.62),
            (1150, 0.92),
            (1450, 1.00),
            (3000, 1.00),
        ]
        # Nature Paper mode points
        self.ssd_opacity_points_nature = [
            (-1000, 0.00),
            (500, 0.00),
            (700, 0.15),   # Semi-transparent cortical bone shell
            (1200, 0.25),
            (3000, 0.30),
        ]
        self.vr_opacity_points_nature = [
            (-1000, 0.00),
            (50, 0.00),
            (100, 0.40),   # Emphasize vascular channels / marrow spaces inside bone
            (250, 0.85),
            (400, 0.95),
            (600, 0.00),   # Drop off before dense bone
        ]
        self.vr_color_points_nature = [
            (-1000, 0.00, 0.00, 0.00),
            (50, 0.80, 0.10, 0.10),   # Deep red for marrow
            (150, 0.95, 0.30, 0.10),  # Bright orange/red for channels
            (300, 1.00, 0.60, 0.20),
            (600, 1.00, 0.80, 0.50),
        ]
        
        self.ssd_opacity_points = list(self.ssd_opacity_points_stable)
        self.ssd_color_points_stable = [
            (-1000, 0.00, 0.00, 0.00),
            (420, 0.80, 0.78, 0.75),
            (760, 0.95, 0.93, 0.90),
            (1300, 1.00, 1.00, 1.00),
            (3000, 1.00, 1.00, 1.00),
        ]
        self.ssd_color_points = list(self.ssd_color_points_stable)
        # Class B (VR Layer): 骨髓腔，低 HU（20-150）
        self.vr_opacity_points = [
            (-1000, 0.00),
            (10, 0.00),
            (20, 0.05),
            (80, 0.16),
            (120, 0.24),
            (150, 0.28),
            (180, 0.10),
            (260, 0.00),
        ]
        self.vr_color_points = [
            (-1000, 0.00, 0.00, 0.00),
            (20, 0.55, 0.18, 0.18),
            (80, 0.72, 0.30, 0.28),
            (120, 0.82, 0.42, 0.36),
            (150, 0.92, 0.56, 0.46),
            (260, 0.95, 0.80, 0.70),
        ]
        # Cinematic 模式下的 VR 传递函数（根据 2026 Thorax/Vascular Spectral Optimized 方案优化）
        self.vr_opacity_points_cinematic = [
            (-1000, 0.00),
            (-950, 0.00),
            (-900, 0.12),  # 肺实质 (紫/靛蓝) 起点
            (-400, 0.20),  # 肺实质 终点
            (-350, 0.00),  # 截断空气与脂肪
            (100, 0.00),   # 增强血管前
            (150, 0.60),   # 增强血管 (高亮黄/金橙) 起点
            (250, 0.90),   # 血管核心
            (550, 0.95),   # 血管终点
            (600, 0.00),   # 交接给骨骼 (SSD)
        ]
        self.vr_color_points_cinematic = [
            (-1000, 0.00, 0.00, 0.00),
            (-950, 0.29, 0.00, 0.51),  # Deep Violet
            (-400, 0.15, 0.00, 0.35),  # Indigo
            (150, 1.00, 0.55, 0.00),   # Golden Orange
            (550, 1.00, 0.96, 0.00),   # Cadmium Yellow
        ]
        
        self.ssd_opacity_points_cinematic = [
            (-1000, 0.00),
            (150, 0.00),
            (200, 0.20),   # 骨骼系统起点
            (500, 0.70),   # 骨皮质
            (1200, 1.00),  # 密质骨
            (3000, 1.00),
        ]
        self.ssd_color_points_cinematic = [
            (-1000, 0.00, 0.00, 0.00),
            (200, 1.00, 0.99, 0.82),   # Pale Yellow Cream
            (1200, 1.00, 1.00, 0.94),  # Ivory
            (3000, 1.00, 1.00, 1.00),  # White
        ]
        
        self.vr_opacity_points_spectral = [
            (-1000, 0.00),
            (-950, 0.00),
            (-900, 0.10),  # Lungs (cyan mist)
            (-500, 0.20),
            (-400, 0.00),
            (-120, 0.00),
            (-100, 0.02),  # Soft tissue (dark cool grey, lower opacity to reduce fatigue)
            (80, 0.02),
            (100, 0.00),
            (150, 0.60),   # Vessels (crimson)
            (250, 0.90),
            (500, 0.95),
            (700, 0.00),
        ]
        self.vr_color_points_spectral = [
            (-1000, 0.00, 0.00, 0.00),
            (-900, 0.20, 0.80, 0.80),  # Cyan
            (-500, 0.40, 0.90, 0.90),
            (-100, 0.18, 0.21, 0.25),  # Cool Dark Grey
            (80, 0.21, 0.23, 0.28),
            (150, 0.50, 0.05, 0.05),   # Deep Crimson
            (250, 0.70, 0.10, 0.10),
            (500, 0.86, 0.87, 0.88),   # Cool Light Grey / bone
        ]

        # Figure 8 mode: 皮质SSD开口 + 骨髓骨性结构拼接
        # SSD: semi-transparent ivory shell with channel openings visible as dark perforations
        self.ssd_opacity_points_figure8 = [
            (-1000, 0.00),
            (300, 0.00),
            (420, 0.06),
            (550, 0.15),
            (700, 0.22),
            (900, 0.28),
            (1100, 0.25),
            (1500, 0.18),
            (3000, 0.12),
        ]
        self.ssd_color_points_figure8 = [
            (-1000, 0.00, 0.00, 0.00),
            (420, 0.85, 0.83, 0.78),
            (900, 0.95, 0.93, 0.90),
            (3000, 1.00, 1.00, 1.00),
        ]
        self.vr_opacity_points_figure8 = [
            (-1000, 0.00),
            (-50, 0.00),
            (0, 0.04),
            (50, 0.38),
            (100, 0.70),
            (200, 0.85),
            (350, 0.90),
            (450, 0.55),
            (550, 0.00),
            (3000, 0.00),
        ]
        self.vr_color_points_figure8 = [
            (-1000, 0.00, 0.00, 0.00),
            (0, 0.35, 0.10, 0.05),
            (50, 0.60, 0.25, 0.12),
            (100, 0.80, 0.45, 0.22),
            (200, 0.95, 0.65, 0.40),
            (350, 1.00, 0.80, 0.55),
            (550, 1.00, 0.90, 0.75),
        ]

        # Layered Channel 模式: 4层虚拟体渲染 (外板/板障/内板/微通道增强)
        # Layer 1+3 (SSD): outer + inner cortical shell, 非常透明
        self.ssd_opacity_points_layered = [
            (-1000, 0.000),
            (400, 0.000),
            (600, 0.025),
            (800, 0.065),
            (1100, 0.100),
            (1500, 0.070),
            (2200, 0.025),
            (3000, 0.012),
        ]
        self.ssd_color_points_layered = [
            (-1000, 0.00, 0.00, 0.00),
            (600, 0.78, 0.80, 0.84),
            (1100, 0.88, 0.90, 0.93),
            (3000, 0.96, 0.97, 0.99),
        ]
        # Layer 2 (VR): 12点非线性骨髓TF — 覆盖黄骨髓→红骨髓→骨小梁全动态范围
        self.vr_opacity_points_layered = [
            (-1000, 0.000),
            (-120, 0.000),           # 黄骨髓起点
            (-100, 0.015),           # 淡黄可见
            (-60,  0.040),           # 黄骨髓峰
            (-20,  0.100),           # 红骨髓爬升
            (0,    0.080),           # 纯细胞区微降
            (30,   0.120),           # 红骨髓峰
            (60,   0.160),           # 骨髓-骨小梁过渡
            (100,  0.220),           # 骨小梁起点
            (180,  0.300),           # 骨小梁峰
            (280,  0.260),           # 致密骨小梁
            (400,  0.120),           # 皮质过渡
            (500,  0.030),           # 皮质渐隐
            (600,  0.000),
        ]
        self.vr_color_points_layered = [
            (-1000, 0.00, 0.00, 0.00),
            (-100,  0.55, 0.48, 0.25),   # 淡黄
            (-60,   0.60, 0.52, 0.30),   # 暖黄
            (-20,   0.72, 0.30, 0.20),   # 红过渡
            (0,     0.75, 0.22, 0.18),   # 深红 (造血)
            (30,    0.80, 0.25, 0.20),   # 亮红
            (60,    0.85, 0.38, 0.28),   # 红琥珀
            (100,   0.90, 0.50, 0.35),   # 琥珀
            (180,   0.95, 0.65, 0.45),   # 金琥珀
            (280,   0.98, 0.78, 0.58),   # 浅琥珀
            (400,   1.00, 0.88, 0.75),   # 骨白
            (500,   1.00, 0.92, 0.82),   # 亮骨白
        ]
        # Layer 4 gradient opacity: 微通道边缘增强 (aggressive edge detection)
        self.gradient_opacity_points_layered = [
            (0.0, 0.00),
            (2.0, 0.00),
            (5.0, 0.18),
            (12.0, 0.48),
            (30.0, 0.78),
            (80.0, 0.95),
            (200.0, 1.00),
        ]

        # Frangi Channel 模式: 4层虚拟模型 + Frangi Dark Tube 微通道增强
        # SSD Layer: 超薄骨皮质壳，透明以显示微通道开口
        self.ssd_opacity_points_frangi = [
            (-1000, 0.000),
            (400, 0.000),
            (600, 0.020),
            (800, 0.050),
            (1100, 0.080),
            (1600, 0.050),
            (2200, 0.018),
            (3000, 0.008),
        ]
        self.ssd_color_points_frangi = [
            (-1000, 0.00, 0.00, 0.00),
            (600, 0.72, 0.75, 0.80),
            (1100, 0.85, 0.88, 0.92),
            (3000, 0.95, 0.96, 0.98),
        ]
        # VR Layer: 12点骨髓TF + Frangi-boosted微通道 (青色高亮)
        self.vr_opacity_points_frangi = [
            (-1000, 0.000),
            (-120, 0.000),  (-100, 0.015),  (-60,  0.040),
            (-20,  0.100),  (0,    0.080),  (30,   0.120),
            (60,   0.160),  (100,  0.220),  (180,  0.300),
            (280,  0.260),  (400,  0.120),  (500,  0.030),
            (600,  0.000),
            (1150, 0.000),
            (1250, 0.600),  (1400, 0.880),  (1600, 0.920),
            (1850, 0.350),  (2000, 0.000),  (3000, 0.000),
        ]
        self.vr_color_points_frangi = [
            (-1000, 0.00, 0.00, 0.00),
            (-100,  0.55, 0.48, 0.25),  (-60,   0.60, 0.52, 0.30),
            (-20,   0.72, 0.30, 0.20),  (0,     0.75, 0.22, 0.18),
            (30,    0.80, 0.25, 0.20),  (60,    0.85, 0.38, 0.28),
            (100,   0.90, 0.50, 0.35),  (180,   0.95, 0.65, 0.45),
            (280,   0.98, 0.78, 0.58),  (400,   1.00, 0.88, 0.75),
            (500,   1.00, 0.92, 0.82),
            (1150, 0.00, 0.00, 0.00),
            (1250, 0.00, 0.85, 0.90),  (1400, 0.05, 0.95, 0.88),
            (1600, 0.00, 1.00, 0.70),  (1850, 0.10, 0.70, 0.60),
        ]
        # Gradient opacity: 微通道边缘增强
        self.gradient_opacity_points_frangi = [
            (0.0, 0.00),
            (2.0, 0.00),
            (5.0, 0.15),
            (15.0, 0.45),
            (35.0, 0.75),
            (80.0, 0.95),
            (200.0, 1.00),
        ]

        # Bone Monochrome 模式: 纯VR — 皮质结构突出，髓质半透明衬托
        self.ssd_opacity_points_bone_mono = [(-1000, 0.0), (3000, 0.0)]
        self.ssd_color_points_bone_mono = [(-1000, 0.0, 0.0, 0.0), (3000, 0.0, 0.0, 0.0)]
        self.vr_opacity_points_bone_mono = [
            (-1000, 0.000),
            (-120, 0.000),
            (-100, 0.180),   # 黄骨髓淡入
            (-50,  0.350),   # 黄髓半透明
            (-20,  0.550),   # 红髓中透
            (30,   0.720),   # 红髓密致
            (100,  0.850),   # 骨小梁
            (250,  0.920),   # 骨小梁峰
            (400,  1.000),   # 皮质骨 ▸ 完全不透明
            (800,  1.000),   # 密质骨
            (1500, 1.000),   # 超密骨
            (3000, 1.000),
        ]
        self.vr_color_points_bone_mono = [
            (-1000, 0.00, 0.00, 0.00),
            (-100, 0.55, 0.52, 0.48),   # 冷骨色
            (-20,  0.65, 0.63, 0.60),   # 暖灰骨
            (30,   0.72, 0.70, 0.68),   # 骨本色
            (100,  0.82, 0.81, 0.79),   # 浅骨色
            (400,  0.94, 0.94, 0.93),   # 瓷白 ▸ 皮质
            (1000, 1.00, 1.00, 1.00),   # 纯白
        ]
        self.gradient_opacity_points_bone_mono = [
            (0.0, 1.00),
            (50.0, 1.00),
        ]
        self.vr_opacity_points_bone_mono_frangi = [
            (-1000, 0.000), (-120, 0.000),
            (-100, 0.180),  (-50, 0.350),  (-20, 0.550),
            (30, 0.720),    (100, 0.850),  (250, 0.920),
            (400, 1.000),   (800, 1.000),
            (1150, 0.000),  (1250, 0.800), (1500, 1.000),
            (1850, 1.000),  (2000, 0.000),  (3000, 1.000),
        ]
        self.vr_color_points_bone_mono_frangi = [
            (-1000, 0.00, 0.00, 0.00),
            (-100, 0.55, 0.52, 0.48),
            (-20,  0.65, 0.63, 0.60),
            (30,   0.72, 0.70, 0.68),
            (100,  0.82, 0.81, 0.79),
            (400,  0.94, 0.94, 0.93),
            (1000, 1.00, 1.00, 1.00),
            (1150, 0.00, 0.00, 0.00), (1250, 0.92, 0.90, 0.88),
            (1850, 1.00, 1.00, 1.00),
        ]

        # 2D TF (Kniss 2001) 模式: 2D TF预处理后VR — 骨+界面仅存, 骨髓/软组织远场已衰减
        self.vr_opacity_points_2dtf = [
            (-1000, 0.000),
            (-120, 0.000), (-100, 0.300),
            (-30,  0.600),  (100,  0.900),
            (400,  1.000),  (3000, 1.000),
        ]
        self.vr_color_points_2dtf = [
            (-1000, 0.00, 0.00, 0.00),
            (-100, 0.45, 0.42, 0.37),
            (0, 0.65, 0.62, 0.58),
            (300, 0.92, 0.90, 0.87),
            (800, 1.00, 1.00, 1.00),
        ]

        self._build_ui()
        if self.initial_input and os.path.exists(self.initial_input):
            self.path_edit.line_edit().setText(self.initial_input)
            self.load_dicom()

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget(self)
        root_layout = QtWidgets.QVBoxLayout(central)

        # --- Tab widget for pages ---
        self.pages = QtWidgets.QTabWidget()

        # === Tab 0: 渲染 (Render) ===
        render_page = QtWidgets.QWidget()
        render_layout = QtWidgets.QVBoxLayout(render_page)
        render_layout.setContentsMargins(4, 2, 4, 2)
        render_layout.setSpacing(1)

        # --- 路径输入 ---
        self.path_edit = CLineEdit(master=render_page, placeholder_text="DICOM 目录路径，或选择单个 .dcm 文件...")
        render_layout.addWidget(self.path_edit)
        btn_row = QtWidgets.QHBoxLayout()
        self.btn_pick_dir = CButton(master=render_page, width=66, text="选文件夹", command=self.pick_dir)
        self.btn_pick_file = CButton(master=render_page, width=56, text="选文件", command=self.pick_file)
        self.btn_load = CButton(master=render_page, width=66, text="加载渲染", command=self.load_dicom,
                                 background_color=("#782838", "#8a3448"),
                                 hover_color=("#8e3848", "#9e4858"),
                                 text_color=("#ffffff", "#ffffff"))
        btn_row.addWidget(self.btn_pick_dir)
        btn_row.addWidget(self.btn_pick_file)
        btn_row.addWidget(self.btn_load)
        btn_row.addStretch()
        render_layout.addLayout(btn_row)

        # --- 窗宽窗位 ---
        render_layout.addWidget(QtWidgets.QLabel("窗位 (Window Level) 偏移"))
        self.wl_slider = CSlider(master=render_page, minimum=-1000, maximum=1000, value=0)
        self.wl_label = QtWidgets.QLabel("当前: 0 HU")
        self.wl_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        render_layout.addWidget(self.wl_slider)
        render_layout.addWidget(self.wl_label)

        render_layout.addWidget(QtWidgets.QLabel("窗宽 (Window Width) 缩放"))
        self.ww_slider = CSlider(master=render_page, minimum=10, maximum=300, value=100)
        self.ww_label = QtWidgets.QLabel("当前: 1.00x")
        self.ww_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        render_layout.addWidget(self.ww_slider)
        render_layout.addWidget(self.ww_label)

        # --- SSD ---
        render_layout.addWidget(QtWidgets.QLabel("SSD 骨骼层不透明度"))
        self.ssd_slider = CSlider(master=render_page, minimum=0, maximum=200, value=90)
        self.ssd_slider_label = QtWidgets.QLabel("当前: 0.90")
        self.ssd_slider_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        render_layout.addWidget(self.ssd_slider)
        render_layout.addWidget(self.ssd_slider_label)

        render_layout.addWidget(QtWidgets.QLabel("SSD 阈值范围"))
        self.ssd_threshold_slider = RangeSlider()
        self.ssd_threshold_slider.setRange(-1000, 3000)
        self.ssd_threshold_slider.setValues(320, 1300)
        self.ssd_threshold_slider.valueChanged.connect(self.on_ssd_threshold_change)
        self.ssd_threshold_label = QtWidgets.QLabel("当前: [320, 1300]")
        self.ssd_threshold_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        render_layout.addWidget(self.ssd_threshold_slider)
        render_layout.addWidget(self.ssd_threshold_label)

        # --- VR ---
        render_layout.addWidget(QtWidgets.QLabel("VR 软组织层不透明度"))
        self.vr_slider = CSlider(master=render_page, minimum=0, maximum=200, value=20)
        self.vr_slider_label = QtWidgets.QLabel("当前: 0.90")
        self.vr_slider_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        render_layout.addWidget(self.vr_slider)
        render_layout.addWidget(self.vr_slider_label)

        # --- 渲染模式 ---
        mode_row = QtWidgets.QHBoxLayout()
        mode_row.addWidget(QtWidgets.QLabel("渲染模式"))
        self.mode_combo = CComboBox(master=render_page, values=[
            "稳定渲染模式 (CPU/基础)",
            "高清骨表面模式 (GPU)",
            "CR 电影级渲染模式",
            "Nature 颅骨微通道模式 (PDF)",
            "Figure8 皮质开口/骨髓拼接模式",
            "Layered 分层体渲染 (微通道增强)",
            "Frangi 微通道增强 (Dark Tube)",
            "骨组织固有色渲染 (Bone Monochrome)",
            "2D TF 界面分离 (Kniss 2001)",
            "CR 光谱模式 (Spectral Look)",
            "Exposure Render (CUDA)",
            "双容积模式 (Dual Volume)",
        ])
        mode_row.addWidget(self.mode_combo, 1)
        render_layout.addLayout(mode_row)

        # --- 裁剪与背景 ---
        util_row = QtWidgets.QHBoxLayout()
        self.check_crop = QtWidgets.QCheckBox("启用裁剪框")
        self.btn_bg_toggle = CButton(master=render_page, width=90, text="切换背景", command=self.toggle_background)
        self.bg_is_white = False
        util_row.addWidget(self.check_crop)
        util_row.addWidget(self.btn_bg_toggle)
        util_row.addStretch()
        render_layout.addLayout(util_row)

        # --- Slicer 预设 ---
        preset_row = QtWidgets.QHBoxLayout()
        preset_row.addWidget(QtWidgets.QLabel("Slicer 预设模板"))
        self.preset_combo = QtWidgets.QComboBox()
        self.preset_combo.addItem("None (使用滑块调节)")
        for preset_name in sorted(self.slicer_presets.keys()):
            self.preset_combo.addItem(preset_name)
        self.preset_combo.currentIndexChanged.connect(self.on_preset_change)
        preset_row.addWidget(self.preset_combo, 1)
        render_layout.addLayout(preset_row)

        # --- 预处理 ---
        self.check_nlm = QtWidgets.QCheckBox("NLM 降噪 (保留微通道边缘)")
        self.check_nlm.stateChanged.connect(self.on_preproc_change)
        render_layout.addWidget(self.check_nlm)

        self.check_clahe = QtWidgets.QCheckBox("CLAHE 局部对比度增强")
        self.check_clahe.stateChanged.connect(self.on_preproc_change)
        render_layout.addWidget(self.check_clahe)

        self.check_frangi = QtWidgets.QCheckBox("Frangi 微通道检测 (Dark Tube)")
        self.check_frangi.stateChanged.connect(self.on_preproc_change)
        render_layout.addWidget(self.check_frangi)

        self.check_dist = QtWidgets.QCheckBox("距离场骨膜聚合 (Distance-Based)")
        self.check_dist.stateChanged.connect(self.on_preproc_change)
        render_layout.addWidget(self.check_dist)

        self.check_2dtf = QtWidgets.QCheckBox("2D TF 骨界面分离 (Kniss 2001)")
        self.check_2dtf.stateChanged.connect(self.on_preproc_change)
        render_layout.addWidget(self.check_2dtf)

        vram_row = QtWidgets.QHBoxLayout()
        vram_row.addWidget(QtWidgets.QLabel("VRAM 限额"))
        self.vram_spin = QtWidgets.QSpinBox()
        self.vram_spin.setRange(1, 48)
        self.vram_spin.setValue(10)
        self.vram_spin.setSuffix(" GB")
        self.vram_spin.valueChanged.connect(self.on_vram_change)
        vram_row.addWidget(self.vram_spin)
        vram_row.addStretch()
        render_layout.addLayout(vram_row)

        self.check_cpu = QtWidgets.QCheckBox("CPU 全分辨率渲染 (跳过下采样)")
        self.check_cpu.setChecked(False)
        self.check_cpu.stateChanged.connect(self.on_cpu_change)
        render_layout.addWidget(self.check_cpu)

        # --- VR 阈值 ---
        render_layout.addWidget(QtWidgets.QLabel("VR 阈值范围 1"))
        self.vr_threshold_slider = RangeSlider()
        self.vr_threshold_slider.setRange(-1000, 3000)
        self.vr_threshold_slider.setValues(20, 150)
        self.vr_threshold_slider.valueChanged.connect(self.on_vr_threshold_change)
        self.vr_threshold_label = QtWidgets.QLabel("当前: [20, 150]")
        self.vr_threshold_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        render_layout.addWidget(self.vr_threshold_slider)
        render_layout.addWidget(self.vr_threshold_label)

        render_layout.addWidget(QtWidgets.QLabel("VR 阈值范围 2"))
        self.vr_threshold_slider2 = RangeSlider()
        self.vr_threshold_slider2.setRange(-1000, 3000)
        self.vr_threshold_slider2.setValues(-200, -50)
        self.vr_threshold_slider2.valueChanged.connect(self.on_vr_threshold_change)
        self.vr_threshold_label2 = QtWidgets.QLabel("当前: [-200, -50]")
        self.vr_threshold_label2.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        render_layout.addWidget(self.vr_threshold_slider2)
        render_layout.addWidget(self.vr_threshold_label2)

        # --- 渲染参数 ---
        render_layout.addWidget(QtWidgets.QLabel("Monte Carlo 质量"))
        self.mc_slider = CSlider(master=render_page, minimum=10, maximum=100, value=60)
        self.mc_label = QtWidgets.QLabel("当前: 0.60")
        self.mc_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        render_layout.addWidget(self.mc_slider)
        render_layout.addWidget(self.mc_label)

        render_layout.addWidget(QtWidgets.QLabel("散射混合强度"))
        self.scatter_slider = CSlider(master=render_page, minimum=0, maximum=100, value=65)
        self.scatter_label = QtWidgets.QLabel("当前: 0.65")
        self.scatter_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        render_layout.addWidget(self.scatter_slider)
        render_layout.addWidget(self.scatter_label)

        render_layout.addWidget(QtWidgets.QLabel("各向异性参数 (g)"))
        self.g_slider = CSlider(master=render_page, minimum=0, maximum=95, value=80)
        self.g_label = QtWidgets.QLabel("当前: 0.80")
        self.g_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        render_layout.addWidget(self.g_slider)
        render_layout.addWidget(self.g_label)

        render_layout.addWidget(QtWidgets.QLabel("曝光系数 (Exposure)"))
        self.exp_slider = CSlider(master=render_page, minimum=20, maximum=300, value=150)
        self.exp_label = QtWidgets.QLabel("当前: 1.50")
        self.exp_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        render_layout.addWidget(self.exp_slider)
        render_layout.addWidget(self.exp_label)

        render_layout.addWidget(QtWidgets.QLabel("CR 降噪强度"))
        self.denoise_slider = CSlider(master=render_page, minimum=0, maximum=100, value=0)
        self.denoise_label = QtWidgets.QLabel("当前: 0.00")
        self.denoise_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        render_layout.addWidget(self.denoise_slider)
        render_layout.addWidget(self.denoise_label)

        render_layout.addWidget(QtWidgets.QLabel("主光线采样步长 (Primary)"))
        self.primary_slider = CSlider(master=render_page, minimum=1, maximum=100, value=10)
        self.primary_label = QtWidgets.QLabel("当前: 0.10")
        self.primary_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        render_layout.addWidget(self.primary_slider)
        render_layout.addWidget(self.primary_label)

        render_layout.addWidget(QtWidgets.QLabel("阴影光线采样步长 (Shadow)"))
        self.shadow_slider = CSlider(master=render_page, minimum=1, maximum=100, value=10)
        self.shadow_label = QtWidgets.QLabel("当前: 0.10")
        self.shadow_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        render_layout.addWidget(self.shadow_slider)
        render_layout.addWidget(self.shadow_label)

        # --- DoF & BG Light ---
        dof_row = QtWidgets.QHBoxLayout()
        self.cr_dof_checkbox = QtWidgets.QCheckBox("景深 (Depth of Field)")
        self.cr_dof_checkbox.stateChanged.connect(self.on_cr_params_change)
        dof_row.addWidget(self.cr_dof_checkbox)
        self.cr_dof_radius_slider = CSlider(master=render_page, minimum=0, maximum=50, value=10)
        self.cr_dof_radius_slider.slider().valueChanged.connect(self.on_cr_params_change)
        dof_row.addWidget(self.cr_dof_radius_slider, 1)
        render_layout.addLayout(dof_row)

        self.cr_bg_checkbox = QtWidgets.QCheckBox("使用背景光源")
        self.cr_bg_checkbox.stateChanged.connect(self.on_cr_params_change)
        render_layout.addWidget(self.cr_bg_checkbox)

        # --- 连接滑块信号 ---
        self.denoise_slider.slider().valueChanged.connect(self.on_cr_params_change)

        # --- 加载进度 ---
        progress_group = QtWidgets.QGroupBox("加载进度")
        progress_group.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
        progress_layout = QtWidgets.QVBoxLayout(progress_group)
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_text = QtWidgets.QTextEdit()
        self.progress_text.setReadOnly(True)
        self.progress_text.setMinimumHeight(50)
        self.progress_text.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addWidget(self.progress_text, 1)
        render_layout.addWidget(progress_group)

        # render_page goes in its own scroll area for the tab
        render_scroll = QtWidgets.QScrollArea()
        render_scroll.setWidgetResizable(True)
        render_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        render_scroll.setWidget(render_page)
        self.pages.addTab(render_scroll, "渲染")

        # === Tab 1: 分割 (Segmentation) ===
        segment_page = QtWidgets.QWidget()
        segment_layout = QtWidgets.QVBoxLayout(segment_page)

        seg_hu_layout = QtWidgets.QHBoxLayout()
        seg_hu_layout.addWidget(QtWidgets.QLabel("HU窗口下限:"))
        self.seg_hu_low = QtWidgets.QSpinBox()
        self.seg_hu_low.setRange(-1000, 3000)
        self.seg_hu_low.setValue(DEFAULT_HU_WINDOW[0])
        self.seg_hu_low.setSuffix(" HU")
        seg_hu_layout.addWidget(self.seg_hu_low)
        seg_hu_layout.addWidget(QtWidgets.QLabel("上限:"))
        self.seg_hu_high = QtWidgets.QSpinBox()
        self.seg_hu_high.setRange(-1000, 3000)
        self.seg_hu_high.setValue(DEFAULT_HU_WINDOW[1])
        self.seg_hu_high.setSuffix(" HU")
        seg_hu_layout.addWidget(self.seg_hu_high)
        seg_hu_layout.addStretch()
        segment_layout.addLayout(seg_hu_layout)

        seg_spacing_layout = QtWidgets.QHBoxLayout()
        seg_spacing_layout.addWidget(QtWidgets.QLabel("重采样间距:"))
        self.seg_spacing_combo = QtWidgets.QComboBox()
        self.seg_spacing_combo.addItems(["0.5 mm", "0.6 mm", "0.8 mm", "不移采样"])
        self.seg_spacing_combo.setCurrentIndex(1)
        seg_spacing_layout.addWidget(self.seg_spacing_combo)
        seg_spacing_layout.addWidget(QtWidgets.QLabel("SAM Clicks:"))
        self.seg_clicks = QtWidgets.QSpinBox()
        self.seg_clicks.setRange(1, 5)
        self.seg_clicks.setValue(DEFAULT_NUM_CLICKS)
        seg_spacing_layout.addWidget(self.seg_clicks)
        seg_spacing_layout.addWidget(QtWidgets.QLabel("阈值:"))
        self.seg_threshold = QtWidgets.QDoubleSpinBox()
        self.seg_threshold.setRange(0.05, 0.95)
        self.seg_threshold.setSingleStep(0.05)
        self.seg_threshold.setValue(DEFAULT_THRESHOLD)
        self.seg_threshold.setDecimals(2)
        seg_spacing_layout.addWidget(self.seg_threshold)
        seg_spacing_layout.addStretch()
        segment_layout.addLayout(seg_spacing_layout)

        seg_post_layout = QtWidgets.QHBoxLayout()
        self.seg_check_cc = QtWidgets.QCheckBox("连通域过滤 (最小体素)")
        self.seg_check_cc.setChecked(True)
        self.seg_cc_size = QtWidgets.QSpinBox()
        self.seg_cc_size.setRange(10, 100000)
        self.seg_cc_size.setValue(DEFAULT_MIN_COMPONENT_SIZE)
        self.seg_cc_size.setSingleStep(100)
        seg_post_layout.addWidget(self.seg_check_cc)
        seg_post_layout.addWidget(self.seg_cc_size)
        self.seg_check_close = QtWidgets.QCheckBox("形态学闭运算 (核大小)")
        self.seg_check_close.setChecked(True)
        self.seg_close_kernel = QtWidgets.QSpinBox()
        self.seg_close_kernel.setRange(1, 10)
        self.seg_close_kernel.setValue(DEFAULT_CLOSING_KERNEL)
        seg_post_layout.addWidget(self.seg_check_close)
        seg_post_layout.addWidget(self.seg_close_kernel)
        seg_post_layout.addStretch()
        segment_layout.addLayout(seg_post_layout)

        seg_vis_layout = QtWidgets.QHBoxLayout()
        self.seg_check_surface = QtWidgets.QCheckBox("显示血管表面")
        self.seg_check_surface.setChecked(True)
        self.seg_check_volume = QtWidgets.QCheckBox("半透明体积渲染")
        seg_vis_layout.addWidget(self.seg_check_surface)
        seg_vis_layout.addWidget(self.seg_check_volume)
        seg_vis_layout.addStretch()
        segment_layout.addLayout(seg_vis_layout)

        seg_btn_layout = QtWidgets.QHBoxLayout()
        self.seg_btn_start = CButton(master=segment_page, width=80, text="▶ 开始分割",
                                      command=self.on_seg_start,
                                      background_color=("#782838", "#8a3448"),
                                      hover_color=("#8e3848", "#9e4858"),
                                      text_color=("#ffffff", "#ffffff"))
        self.seg_btn_cancel = CButton(master=segment_page, width=70, text="⏹ 停止",
                                      command=self.on_seg_cancel,
                                      background_color=("#402020", "#4e2828"),
                                      hover_color=("#503030", "#5e3838"))
        self.seg_btn_clear = CButton(master=segment_page, width=70, text="🗑 清除覆盖",
                                     command=self.on_seg_clear,
                                     background_color=("#303040", "#3c3c4e"),
                                     hover_color=("#404050", "#4c4c5e"))
        self.seg_btn_clear.setEnabled(False)
        seg_btn_layout.addWidget(self.seg_btn_start)
        seg_btn_layout.addWidget(self.seg_btn_cancel)
        seg_btn_layout.addWidget(self.seg_btn_clear)
        seg_btn_layout.addStretch()
        segment_layout.addLayout(seg_btn_layout)

        seg_progress_group = QtWidgets.QGroupBox("分割进度")
        seg_progress_layout = QtWidgets.QVBoxLayout(seg_progress_group)
        self.seg_progress_bar = QtWidgets.QProgressBar()
        self.seg_progress_bar.setRange(0, 100)
        self.seg_progress_bar.setValue(0)
        self.seg_progress_label = QtWidgets.QLabel("就绪")
        seg_progress_layout.addWidget(self.seg_progress_bar)
        seg_progress_layout.addWidget(self.seg_progress_label)
        segment_layout.addWidget(seg_progress_group)

        self.seg_stats_group = QtWidgets.QGroupBox("分割结果")
        self.seg_stats_group.setVisible(False)
        seg_stats_layout = QtWidgets.QHBoxLayout(self.seg_stats_group)
        self.seg_stats_label = QtWidgets.QLabel("")
        seg_stats_layout.addWidget(self.seg_stats_label)
        segment_layout.addWidget(self.seg_stats_group)

        self.pages.addTab(segment_page, "分割")

        # ---- PCCT K-edge 物质渲染标签 ----
        kedge_page = QtWidgets.QWidget()
        kedge_layout = QtWidgets.QVBoxLayout(kedge_page)

        kedge_path_row = QtWidgets.QHBoxLayout()
        self.kedge_dir_edit = CLineEdit(master=kedge_page, width=280, text=r"C:\Users\chris\Desktop\SSD+VR\kedge_output")
        self.btn_run_kedge = CButton(master=kedge_page, width=120, text="运行 K-edge 预处理", command=self._run_kedge_preprocess)
        self.btn_load_kedge = CButton(master=kedge_page, width=80, text="加载 NIfTI", command=self._load_kedge_data)
        kedge_path_row.addWidget(QtWidgets.QLabel("K-edge 目录:"))
        kedge_path_row.addWidget(self.kedge_dir_edit)
        kedge_path_row.addWidget(self.btn_run_kedge)
        kedge_path_row.addWidget(self.btn_load_kedge)

        mat_row = QtWidgets.QHBoxLayout()
        mat_row.addWidget(QtWidgets.QLabel("K-edge 物质:"))
        self.kedge_mat_combo = QtWidgets.QComboBox()
        self.kedge_mat_combo.addItems(["Iodine (碘,33.2keV)", "Gadolinium (钆,50.2keV)",
                                       "Gold (金,80.7keV)", "Bismuth (铋,90.5keV)", "全部叠加"])
        mat_row.addWidget(self.kedge_mat_combo)

        kedge_layout.addLayout(kedge_path_row)
        kedge_layout.addLayout(mat_row)
        self.pages.addTab(kedge_page, "PCCT K-edge")

        # Split layout: left=tabs+controls, right=VTK render
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.addWidget(self.pages)

        self.vtk_widget = QVTKRenderWindowInteractor(central)
        splitter.addWidget(self.vtk_widget)
        splitter.setSizes([480, 1040])
        splitter.setChildrenCollapsible(False)

        root_layout.addWidget(splitter, 1)

        self.setCentralWidget(central)

        self.renderer = vtk.vtkRenderer()
        self.renderer.SetBackground(0.06, 0.02, 0.03)  # Deep wine red
        self.render_window = self.vtk_widget.GetRenderWindow()
        self.render_window.AddRenderer(self.renderer)
        
        # --- VTK 原生性能优化：设置期望的交互帧率 ---
        self.iren = self.render_window.GetInteractor()
        self.iren.SetDesiredUpdateRate(30.0)  # 交互时期望保持 30 帧
        self.iren.SetStillUpdateRate(0.0001)  # 静止时允许更多时间渲染高画质
        
        self.iren.SetInteractorStyle(vtk.vtkInteractorStyleTrackballCamera())

        def on_camera_modified(caller, event):
            if self.render_mode == "exposure_render":
                self._sync_ercore_state()
                
        self.renderer.GetActiveCamera().AddObserver("ModifiedEvent", on_camera_modified)

        self.ssd_slider.slider().valueChanged.connect(self.on_slider_change)
        self.vr_slider.slider().valueChanged.connect(self.on_slider_change)
        self.wl_slider.slider().valueChanged.connect(self.on_ww_wl_change)
        self.ww_slider.slider().valueChanged.connect(self.on_ww_wl_change)
        self.check_crop.toggled.connect(self.on_crop_toggle)
        self.mode_combo.combo_box().currentIndexChanged.connect(self.on_mode_change)
        self.mc_slider.slider().valueChanged.connect(self.on_cr_params_change)
        self.scatter_slider.slider().valueChanged.connect(self.on_cr_params_change)
        self.g_slider.slider().valueChanged.connect(self.on_cr_params_change)
        self.exp_slider.slider().valueChanged.connect(self.on_cr_params_change)
        self.primary_slider.slider().valueChanged.connect(self.on_cr_params_change)
        self.shadow_slider.slider().valueChanged.connect(self.on_cr_params_change)

        self.seg_check_surface.stateChanged.connect(self._on_seg_vis_change)
        self.seg_check_volume.stateChanged.connect(self._on_seg_vis_change)

        self.kedge_mat_combo.currentIndexChanged.connect(self._render_kedge_material)

        self.box_widget = None

        self.iren.Initialize()

        self.seg_renderer = vtk.vtkRenderer()
        self.seg_renderer.SetBackground(0.04, 0.02, 0.03)
        self.seg_renderer.SetViewport(0.0, 0.0, 0.0, 1.0)
        self.render_window.AddRenderer(self.seg_renderer)
        self.kedge_renderer = vtk.vtkRenderer()
        self.kedge_renderer.SetBackground(0.04, 0.02, 0.03)
        self.kedge_renderer.SetViewport(0.0, 0.0, 0.0, 1.0)
        self.render_window.AddRenderer(self.kedge_renderer)
        self.render_window.SetNumberOfLayers(3)
        self.pages.currentChanged.connect(self._on_tab_changed)

    def _on_tab_changed(self, index: int) -> None:
        if index == 0:
            self.renderer.SetViewport(0.0, 0.0, 1.0, 1.0)
            self.seg_renderer.SetViewport(0.0, 0.0, 0.0, 1.0)
            self.kedge_renderer.SetViewport(0.0, 0.0, 0.0, 1.0)
        elif index == 1:
            self.renderer.SetViewport(0.0, 0.0, 0.5, 1.0)
            self.seg_renderer.SetViewport(0.5, 0.0, 1.0, 1.0)
            self.kedge_renderer.SetViewport(0.0, 0.0, 0.0, 1.0)
            cam = self.renderer.GetActiveCamera()
            if cam:
                self.seg_renderer.SetActiveCamera(cam)
        else:
            self.renderer.SetViewport(0.0, 0.0, 0.5, 1.0)
            self.seg_renderer.SetViewport(0.0, 0.0, 0.0, 1.0)
            self.kedge_renderer.SetViewport(0.5, 0.0, 1.0, 1.0)
            cam = self.renderer.GetActiveCamera()
            if cam:
                self.kedge_renderer.SetActiveCamera(cam)
        self.iren.Render()

    def _run_kedge_preprocess(self) -> None:
        from vtkmodules.util import numpy_support
        import subprocess, sys
        script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kedge_preprocess.py")
        if not os.path.exists(script_path):
            QtWidgets.QMessageBox.warning(self, "脚本不存在", "kedge_preprocess.py 未找到。")
            return
        self.set_progress(0, "K-edge 预处理开始 (约 60-90 分钟)...")
        print(f"运行 K-edge 预处理: {script_path}")
        self.btn_run_kedge.setEnabled(False)
        try:
            proc = subprocess.Popen(
                [sys.executable, script_path],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1
            )
            full_out = []
            while True:
                line = proc.stdout.readline()
                if not line and proc.poll() is not None:
                    break
                if line:
                    line = line.rstrip()
                    print(f"  [kedge] {line}")
                    full_out.append(line)
                    import sys; sys.stdout.flush()
            proc.wait()
            if proc.returncode != 0:
                print(f"K-edge 预处理失败 (exit={proc.returncode})")
                self.set_progress(0, f"K-edge 预处理失败 (exit={proc.returncode})")
            else:
                print(f"K-edge 预处理完成: {len(full_out)} lines")
                self.set_progress(100, "K-edge 预处理完成。点'加载 NIfTI'渲染。")
                self._load_kedge_data()
        except Exception as e:
            print(f"K-edge 预处理异常: {e}")
            self.set_progress(0, f"异常: {e}")
        self.btn_run_kedge.setEnabled(True)

    def _clear_kedge_volumes(self) -> None:
        if self.kedge_renderer is None:
            return
        for name, vol in list(self.kedge_materials.items()):
            self.kedge_renderer.RemoveVolume(vol)
            del vol
        self.kedge_materials = {}
        self.kedge_loaded = False

    def _load_kedge_data(self) -> None:
        kedge_dir = self.kedge_dir_edit.text().strip()
        if not kedge_dir or not os.path.isdir(kedge_dir):
            QtWidgets.QMessageBox.warning(self, "路径无效", "K-edge 目录不存在或无 NIfTI 文件。")
            return

        self._clear_kedge_volumes()
        if self.kedge_renderer is None:
            return

        from vtkmodules.util import numpy_support

        self.set_progress(0, "加载 K-edge NIfTI 数据...")

        for idx, mat_name in enumerate(self.kedge_mat_names):
            nii_path = os.path.join(kedge_dir, f"{mat_name}.nii.gz")
            if not os.path.exists(nii_path):
                print(f"  K-edge {mat_name}: {nii_path} not found, skipping")
                continue
            try:
                import nibabel as nib
                img = nib.load(nii_path)
                nda = np.ascontiguousarray(img.get_fdata(dtype=np.float32).astype(np.int16))
                dims = nda.shape[::-1] if nda.ndim >= 3 else (nda.shape[1], nda.shape[0], 1)
                spacing = img.header.get_zooms()[:3] if len(img.header.get_zooms()) >= 3 else (1, 1, 1)

                # GPU-aware downsampling: same logic as build_reader
                n_vox = int(nda.size)
                est_vram = n_vox * 2 * 2.5 / (1024 ** 3)
                if est_vram > self.vram_threshold_gb * 0.7 or n_vox > 200_000_000:
                    from scipy.ndimage import zoom
                    factor = max(1.0, (n_vox / 80_000_000) ** (1/3))
                    new_z = max(1, int(dims[2] / factor))
                    new_y = max(32, int(dims[1] / factor))
                    new_x = max(32, int(dims[0] / factor))
                    zoom_factors = (new_z / dims[2], new_y / dims[1], new_x / dims[0])
                    nda = zoom(nda, zoom_factors, order=1, mode='nearest').astype(np.int16)
                    dims = (new_x, new_y, new_z)
                    for i in range(3):
                        spacing = list(spacing)
                        spacing[i] = spacing[i] / zoom_factors[i]
                    print(f"  K-edge {mat_name}: downsampled {n_vox/1e6:.0f}M→{nda.size/1e6:.0f}M voxels")

                vtk_data = numpy_support.numpy_to_vtk(nda.ravel(order="C"), deep=True, array_type=vtk.VTK_SHORT)
                vtk_img = vtk.vtkImageData()
                vtk_img.SetDimensions(dims[0], dims[1], dims[2])
                vtk_img.SetSpacing(spacing[0], spacing[1], spacing[2])
                vtk_img.GetPointData().SetScalars(vtk_data)

                mapper = vtk.vtkGPUVolumeRayCastMapper()
                mapper.SetInputData(vtk_img)
                mapper.SetBlendModeToComposite()
                mapper.SetSampleDistance(1.0)
                vram_gb = int(self.vram_threshold_gb * 0.7 * 1024 ** 3)
                if hasattr(mapper, "SetMaxMemoryInBytes"):
                    mapper.SetMaxMemoryInBytes(vram_gb)

                prop = vtk.vtkVolumeProperty()
                prop.ShadeOn()
                prop.SetInterpolationTypeToLinear()
                prop.SetAmbient(0.20)
                prop.SetDiffuse(0.70)
                prop.SetSpecular(0.30)
                prop.SetSpecularPower(30.0)

                color = vtk.vtkColorTransferFunction()
                r, g, b = self.kedge_mat_colors[idx]
                color.AddRGBPoint(-100, 0, 0, 0)
                color.AddRGBPoint(0, r * 0.3, g * 0.3, b * 0.3)
                color.AddRGBPoint(5000, r, g, b)
                color.AddRGBPoint(32767, 1, 1, 1)
                prop.SetColor(color)

                opacity = vtk.vtkPiecewiseFunction()
                opacity.AddPoint(-32768, 0.0)
                opacity.AddPoint(-100, 0.0)
                opacity.AddPoint(0, 0.05)
                opacity.AddPoint(500, 0.60)
                opacity.AddPoint(2000, 0.90)
                opacity.AddPoint(5000, 1.0)
                opacity.AddPoint(32767, 1.0)
                prop.SetScalarOpacity(opacity)

                volume = vtk.vtkVolume()
                volume.SetMapper(mapper)
                volume.SetProperty(prop)
                self.kedge_materials[mat_name] = volume

                print(f"  K-edge loaded {mat_name}: {dims}, {spacing}")
            except Exception as e:
                print(f"  K-edge {mat_name} 加载失败: {e}")
                import traceback
                traceback.print_exc()

        if self.kedge_materials:
            self.kedge_loaded = True
            for vol in self.kedge_materials.values():
                self.kedge_renderer.AddVolume(vol)
            self._render_kedge_material(0)
            self.kedge_renderer.RemoveAllLights()
            key = vtk.vtkLight()
            key.SetLightTypeToSceneLight(); key.SetPositional(False)
            key.SetPosition(-0.7, -0.4, 1.0); key.SetFocalPoint(0, 0, 0)
            key.SetColor(1.00, 0.97, 0.93); key.SetIntensity(1.8)
            self.kedge_renderer.AddLight(key)
            fill = vtk.vtkLight()
            fill.SetLightTypeToSceneLight(); fill.SetPositional(False)
            fill.SetPosition(0.8, 0.2, 0.5); fill.SetFocalPoint(0, 0, 0)
            fill.SetColor(0.92, 0.94, 1.00); fill.SetIntensity(1.0)
            self.kedge_renderer.AddLight(fill)
            self.renderer.ResetCamera()
            self.kedge_renderer.ResetCamera()
            cam = self.renderer.GetActiveCamera()
            if cam:
                self.kedge_renderer.SetActiveCamera(cam)
            self.iren.Render()
            self.set_progress(100, f"K-edge 已加载 {len(self.kedge_materials)}/4 种物质")
        else:
            self.set_progress(0, "K-edge 加载失败: 未找到任何 NIfTI 文件")

    def _render_kedge_material(self, idx: int) -> None:
        if not self.kedge_loaded or self.kedge_renderer is None:
            return
        all_mode = idx >= len(self.kedge_mat_names)
        for mi, mat_name in enumerate(self.kedge_mat_names):
            vol = self.kedge_materials.get(mat_name)
            if vol is None:
                continue
            vol.SetVisibility(all_mode or mi == idx)
        if not all_mode:
            self.set_progress(100, f"K-edge: {self.kedge_mat_labels[idx]}")
        else:
            self.set_progress(100, "K-edge: 全部叠加")
        self.iren.Render()
        current = self.path_edit.line_edit().text().strip() or os.getcwd()
        selected = QtWidgets.QFileDialog.getExistingDirectory(self, "选择 DICOM 序列目录", current)
        if selected:
            self.path_edit.line_edit().setText(selected)

    def pick_dir(self) -> None:
        current = self.path_edit.line_edit().text().strip() or os.getcwd()
        selected = QtWidgets.QFileDialog.getExistingDirectory(self, "选择 DICOM 序列目录", current)
        if selected:
            self.path_edit.line_edit().setText(selected)

    def pick_file(self) -> None:
        current = self.path_edit.line_edit().text().strip() or os.getcwd()
        selected, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择 DICOM 文件", current, "DICOM (*.dcm);;All files (*.*)"
        )
        if selected:
            self.path_edit.line_edit().setText(selected)

    def get_adjusted_points(self, points, wl_offset, ww_scale):
        return [(p[0] * ww_scale + wl_offset,) + p[1:] for p in points]

    def on_ww_wl_change(self, value=None) -> None:
        wl_offset = self.wl_slider.slider().value()
        ww_scale = self.ww_slider.slider().value() / 100.0
        self.wl_label.setText(f"当前: {wl_offset} HU")
        self.ww_label.setText(f"当前: {ww_scale:.2f}x")
        self.on_slider_change(0)

    def _sync_ercore_state(self):
        if not self.er_wrapper:
            return
            
        # Update resolution if needed
        w, h = self.render_window.GetSize()
        if self.er_buffer is None or self.er_buffer.shape[0] != h or self.er_buffer.shape[1] != w:
            self.er_buffer = np.zeros((h, w, 4), dtype=np.uint8)
            import vtkmodules.util.numpy_support as vtk_np
            self.er_image_data.SetDimensions(w, h, 1)
            vtk_array = vtk_np.numpy_to_vtk(num_array=self.er_buffer.ravel(), deep=False, array_type=vtk.VTK_UNSIGNED_CHAR)
            self.er_image_data.GetPointData().SetScalars(vtk_array)
            self.er_wrapper.set_resolution(w, h)
            
        # Sync Camera
        cam = self.renderer.GetActiveCamera()
        pos = np.array(cam.GetPosition())
        target = np.array(cam.GetFocalPoint())
        up = np.array(cam.GetViewUp())
        fov = cam.GetViewAngle()
        clip_near, clip_far = cam.GetClippingRange()
        
        # Transform VTK world coordinates to Exposure Render normalized coordinates
        # ER centers the volume at (0,0,0) and scales the max dimension to 1.0
        dims = self.er_image_data.GetDimensions() # wait, this is screen res!
        # Need volume dimensions!
        if self.current_ssd_volume:
            bounds = self.current_ssd_volume.GetBounds()
            center = np.array([(bounds[0]+bounds[1])/2, (bounds[2]+bounds[3])/2, (bounds[4]+bounds[5])/2])
            phys_size = np.array([bounds[1]-bounds[0], bounds[3]-bounds[2], bounds[5]-bounds[4]])
        else:
            center = np.array([0,0,0])
            phys_size = np.array([1,1,1])
            
        max_size = max(phys_size) if max(phys_size) > 0 else 1.0
        
        er_pos = (pos - center) / max_size
        er_target = (target - center) / max_size
        er_clip_near = clip_near / max_size
        er_clip_far = clip_far / max_size
        
        cam_params = (tuple(er_pos), tuple(er_target), tuple(up), fov, er_clip_near, er_clip_far, self.er_exposure)
        if self.last_cam_params != cam_params:
            self.er_wrapper.set_camera(
                er_pos, er_target, up, fov, er_clip_near, er_clip_far,
                self.er_exposure, 1.0  # gamma
            )
            
            # Setup Cinematic 3-Point Lighting relative to Camera
            import math
            # Calculate view direction (Z) and right vector (X)
            view_dir = er_target - er_pos
            dist = np.linalg.norm(view_dir)
            if dist > 0: view_dir /= dist
            up_vec = up / np.linalg.norm(up) if np.linalg.norm(up) > 0 else up
            right_vec = np.cross(view_dir, up_vec)
            if np.linalg.norm(right_vec) > 0: right_vec /= np.linalg.norm(right_vec)
            
            # Re-orthogonalize up vector
            up_vec = np.cross(right_vec, view_dir)
            
            # Light distance multiplier
            light_dist = dist * 1.5
            
            # Key Light (Top-Right-Front)
            key_pos = er_pos + right_vec * (light_dist * 0.8) + up_vec * (light_dist * 0.8) - view_dir * (light_dist * 0.5)
            key_dir = er_target - key_pos
            key_color = (1.00, 0.98, 0.95)
            key_mult = 300.0  # Path tracing needs high multiplier for area lights
            key_size = (dist * 0.5, dist * 0.5)
            
            # Fill Light (Left-Front, lower intensity, larger area)
            fill_pos = er_pos - right_vec * (light_dist * 1.0) - up_vec * (light_dist * 0.2) - view_dir * (light_dist * 0.2)
            fill_dir = er_target - fill_pos
            fill_color = (0.78, 0.82, 0.95)
            fill_mult = 100.0
            fill_size = (dist * 1.0, dist * 1.0)
            
            # Rim Light (Top-Back, to highlight silhouettes)
            rim_pos = er_target + view_dir * (light_dist * 1.2) + up_vec * (light_dist * 0.8)
            rim_dir = er_target - rim_pos
            rim_color = (1.00, 0.95, 0.88)
            rim_mult = 400.0
            rim_size = (dist * 0.6, dist * 0.6)
            
            self.er_wrapper.setup_lights(
                key_pos, key_dir, key_color, key_mult, key_size,
                fill_pos, fill_dir, fill_color, fill_mult, fill_size,
                rim_pos, rim_dir, rim_color, rim_mult, rim_size
            )
            
            self.er_wrapper.reset_accumulation()
            self.last_cam_params = cam_params

        # Sync Transfer Functions (Fused SSD + VR for Exposure Render)
        wl_offset = self.wl_slider.slider().value()
        ww_scale = self.ww_slider.slider().value() / 100.0
        
        adj_ssd_op = self.get_adjusted_points(self.ssd_opacity_points, wl_offset, ww_scale)
        adj_ssd_co = self.get_adjusted_points(self.ssd_color_points, wl_offset, ww_scale)
        adj_vr_op = self.get_adjusted_points(self.vr_opacity_points, wl_offset, ww_scale)
        adj_vr_co = self.get_adjusted_points(self.vr_color_points, wl_offset, ww_scale)

        ssd_scale = self.ssd_slider.slider().value() / 100.0
        vr_scale = self.vr_slider.slider().value() / 100.0
        eff_ssd_scale = self._effective_ssd_scale(ssd_scale)
        eff_vr_scale = self._effective_vr_scale(vr_scale)

        tf_params = (tuple(adj_ssd_op), tuple(adj_vr_op), tuple(adj_ssd_co), tuple(adj_vr_co), eff_ssd_scale, eff_vr_scale)
        if self.last_tf_params != tf_params:
            er_op_points = []
            er_co_points = []
            
            # Fuse the TF for Exposure Render across the HU range
            for hu in range(-1000, 3001, 20):
                a_ssd = max(0.0, min(1.0, interp_piecewise(adj_ssd_op, hu) * eff_ssd_scale))
                a_vr = max(0.0, min(1.0, interp_piecewise(adj_vr_op, hu) * eff_vr_scale))
                a_mix = 1.0 - (1.0 - a_ssd) * (1.0 - a_vr)
                
                r1, g1, b1 = interp_color(adj_ssd_co, hu)
                r2, g2, b2 = interp_color(adj_vr_co, hu)
                w = a_ssd + a_vr
                if w > 1e-6:
                    r = (r1 * a_ssd + r2 * a_vr) / w
                    g = (g1 * a_ssd + g2 * a_vr) / w
                    b = (b1 * a_ssd + b2 * a_vr) / w
                else:
                    r, g, b = r2, g2, b2
                
                # We do NOT apply exposure pre-multiplication here because ER handles exposure natively in its camera
                er_op_points.append((hu + 32768, a_mix))
                er_co_points.append((hu + 32768, r, g, b))

            self.er_wrapper.update_opacity_tf(er_op_points)
            self.er_wrapper.update_diffuse_tf(er_co_points)
            self.er_wrapper.reset_accumulation()
            self.last_tf_params = tf_params
        
        self.er_wrapper.bind_tracer()

    def on_slider_change(self, value: int) -> None:
        ssd_scale = self.ssd_slider.slider().value() / 100.0
        vr_scale = self.vr_slider.slider().value() / 100.0
        self.ssd_slider_label.setText(f"当前: {ssd_scale:.2f}")
        self.vr_slider_label.setText(f"当前: {vr_scale:.2f}")
        
        wl_offset = self.wl_slider.slider().value()
        ww_scale = self.ww_slider.slider().value() / 100.0
        
        adj_ssd_op = self.get_adjusted_points(self.ssd_opacity_points, wl_offset, ww_scale)
        adj_ssd_co = self.get_adjusted_points(self.ssd_color_points, wl_offset, ww_scale)
        adj_vr_op = self.get_adjusted_points(self.vr_opacity_points, wl_offset, ww_scale)
        adj_vr_co = self.get_adjusted_points(self.vr_color_points, wl_offset, ww_scale)

        if self.current_ssd_volume is not None:
            self.current_ssd_volume.GetProperty().SetScalarOpacity(make_opacity(adj_ssd_op, self._effective_ssd_scale(ssd_scale)))
            self.current_ssd_volume.GetProperty().SetColor(make_color(adj_ssd_co))
        if self.current_vr_volume is not None:
            self.current_vr_volume.GetProperty().SetScalarOpacity(make_opacity(adj_vr_op, self._effective_vr_scale(vr_scale)))
            self.current_vr_volume.GetProperty().SetColor(make_color(adj_vr_co))

        if self.controller is not None:
            self.controller.ssd_points = adj_ssd_op
            self.controller.vr_points = adj_vr_op
            self.controller.ssd_color_points = adj_ssd_co
            self.controller.vr_color_points = adj_vr_co
            self.controller.update(
                self._effective_ssd_scale(ssd_scale),
                self._effective_vr_scale(vr_scale),
                self.er_exposure,
            )
            self._apply_cr_runtime_params()
            self._sync_ercore_state()
            self.render_window.Render()

    def on_cr_params_change(self, value=None):
        self.mc_quality = self.mc_slider.slider().value() / 100.0
        self.scatter_blend = self.scatter_slider.slider().value() / 100.0
        self.scatter_g = self.g_slider.slider().value() / 100.0
        self.er_exposure = self.exp_slider.slider().value() / 100.0
        self.cr_denoise = self.denoise_slider.slider().value() / 100.0
        self.step_factor_primary = self.primary_slider.slider().value() / 100.0
        self.step_factor_shadow = self.shadow_slider.slider().value() / 100.0

        self.mc_label.setText(f"当前: {self.mc_quality:.2f}")
        self.scatter_label.setText(f"当前: {self.scatter_blend:.2f}")
        self.g_label.setText(f"当前: {self.scatter_g:.2f}")
        self.exp_label.setText(f"当前: {self.er_exposure:.2f}")
        self.denoise_label.setText(f"当前: {self.cr_denoise:.2f}")
        self.primary_label.setText(f"当前: {self.step_factor_primary:.2f}")
        self.shadow_label.setText(f"当前: {self.step_factor_shadow:.2f}")
        
        # Update render parameters
        if self.render_mode in ("cinematic", "nature_channels", "spectral", "figure8_channels", "layer_channel", "frangi_channel"):
            dof_enabled = self.cr_dof_checkbox.isChecked()
            dof_radius = self.cr_dof_radius_slider.slider().value()
            bg_light_enabled = self.cr_bg_checkbox.isChecked()

            # Depth of Field (DoF) Settings
            camera = self.renderer.GetActiveCamera()
            if hasattr(camera, 'SetFocalDisk'):
                camera.SetFocalDisk(dof_radius if dof_enabled else 0.0)
                if dof_enabled:
                    bounds = self.renderer.ComputeVisiblePropBounds()
                    if bounds:
                        focal_dist = ((bounds[1]-bounds[0])**2 + (bounds[3]-bounds[2])**2 + (bounds[5]-bounds[4])**2)**0.5 / 2.0
                        camera.SetFocalDistance(focal_dist)


        if self.controller is not None:
            self.controller.update(
                self._effective_ssd_scale(self.ssd_slider.slider().value() / 100.0),
                self._effective_vr_scale(self.vr_slider.slider().value() / 100.0),
                self.er_exposure,
            )
        self._apply_light_rig_for_mode()
        self._apply_cr_runtime_params()
        self._sync_ercore_state()
        self.render_window.Render()

    def _path_tracing_sample_distance(self) -> float:
        # 限制最小步长以防止 GPU 驱动因单帧计算超时 (TDR) 而崩溃
        # 强制缩小采样距离，固定为最小体素间距的 0.5 倍
        min_spacing = 1.0
        if getattr(self, "image_data", None):
            spacing = self.image_data.GetSpacing()
            min_spacing = min(spacing)
        
        sf = max(0.10, self.step_factor_primary)
        q = max(0.20, self.mc_quality)
        base_dist = max(0.5, min(2.5, 1.5 * sf / q))
        
        # 采用较小值以确保精细度
        return min(base_dist, min_spacing * 0.5)

    def _effective_vr_scale(self, vr_scale: float) -> float:
        if self.render_mode in ("cinematic", "spectral"):
            return max(1.10, min(4.0, vr_scale * 2.6))
        if self.render_mode == "figure8_channels":
            return max(1.00, min(3.5, vr_scale * 2.2))
        if self.render_mode == "layer_channel":
            return max(0.90, min(3.2, vr_scale * 2.8))
        if self.render_mode == "frangi_channel":
            return max(0.85, min(3.0, vr_scale * 3.0))
        if self.render_mode == "bone_mono":
            return max(0.90, min(3.2, vr_scale * 2.5))
        if self.render_mode == "2dtf":
            return max(0.85, min(3.0, vr_scale * 2.2))
        return vr_scale

    def _effective_ssd_scale(self, ssd_scale: float) -> float:
        if self.render_mode in ("cinematic", "spectral"):
            return max(0.20, min(1.20, ssd_scale * 0.45))
        if self.render_mode == "figure8_channels":
            return max(0.25, min(1.30, ssd_scale * 0.55))
        if self.render_mode == "layer_channel":
            return max(0.18, min(0.90, ssd_scale * 0.40))
        if self.render_mode == "frangi_channel":
            return max(0.15, min(0.80, ssd_scale * 0.35))
        if self.render_mode == "bone_mono":
            return max(0.20, min(0.85, ssd_scale * 0.45))
        if self.render_mode == "2dtf":
            return max(0.15, min(0.80, ssd_scale * 0.35))
        return ssd_scale

    def _apply_cr_runtime_params(self) -> None:
        # Default sampling distance is tied to image spacing (typically 0.5 * spacing)
        # to ensure high quality rendering without stepping artifacts.
        sample_distance = 0.5
        if getattr(self, "image_data", None):
            spacing = self.image_data.GetSpacing()
            sample_distance = min(spacing) * 0.5
            
        for mapper in (getattr(self, "current_vr_mapper", None), getattr(self, "current_ssd_mapper", None)):
            if mapper is None:
                continue
            if self.cpu_render:
                if hasattr(mapper, "SetFixedPointBlockSize"):
                    mapper.SetFixedPointBlockSize(128)
                continue
            if hasattr(mapper, "SetSampleDistance"):
                if self.render_mode in ("cinematic", "nature_channels", "spectral", "dual_volume", "exposure_render", "figure8_channels", "layer_channel", "frangi_channel"):
                    mapper.SetSampleDistance(self._path_tracing_sample_distance())
                else:
                    mapper.SetSampleDistance(sample_distance)
            
            if self.render_mode in ("cinematic", "nature_channels", "spectral", "dual_volume", "exposure_render", "figure8_channels", "layer_channel", "frangi_channel"):
                if hasattr(mapper, "SetVolumetricScatteringBlending"):
                    blend = self.scatter_blend * (1.0 - self.cr_denoise * 0.4)
                    mapper.SetVolumetricScatteringBlending(blend)

        if self.render_mode in ("cinematic", "nature_channels", "spectral", "dual_volume", "exposure_render", "figure8_channels", "layer_channel", "frangi_channel"):
                if hasattr(mapper, "SetVolumetricScatteringBlending"):
                    # Denoise optimization: Reduce scattering blend as denoise increases
                    blend = self.scatter_blend * (1.0 - self.cr_denoise * 0.4)
                    mapper.SetVolumetricScatteringBlending(blend)

        if self.render_mode in ("cinematic", "nature_channels", "spectral", "dual_volume", "exposure_render", "figure8_channels", "layer_channel", "frangi_channel"):
            if self.current_vr_volume is not None:
                self.current_vr_volume.GetProperty().SetScatteringAnisotropy(self.scatter_g)
            if self.current_ssd_volume is not None:
                self.current_ssd_volume.GetProperty().SetScatteringAnisotropy(min(0.95, self.scatter_g * 0.8))

    def _configure_ssd_property_by_mode(self, prop: vtk.vtkVolumeProperty) -> None:
        if self.render_mode in ("hd_surface", "cinematic", "nature_channels", "spectral", "dual_volume", "exposure_render", "figure8_channels", "layer_channel", "frangi_channel"):
            prop.ShadeOn()
            if self.render_mode in ("cinematic", "exposure_render", "dual_volume"):
                prop.SetAmbient(0.08)
                prop.SetDiffuse(0.72)
                prop.SetSpecular(0.50)
                prop.SetSpecularPower(50.0)
            elif self.render_mode == "nature_channels":
                prop.SetAmbient(0.15)
                prop.SetDiffuse(0.60)
                prop.SetSpecular(0.60)  # High specular to show glass-like bone contour
                prop.SetSpecularPower(40.0)
            elif self.render_mode == "figure8_channels":
                prop.SetAmbient(0.12)
                prop.SetDiffuse(0.65)
                prop.SetSpecular(0.55)  # Strong specular to highlight surface channel openings
                prop.SetSpecularPower(50.0)
            elif self.render_mode == "layer_channel":
                prop.SetAmbient(0.08)
                prop.SetDiffuse(0.55)
                prop.SetSpecular(0.20)
                prop.SetSpecularPower(16.0)
            elif self.render_mode == "frangi_channel":
                prop.SetAmbient(0.06)
                prop.SetDiffuse(0.50)
                prop.SetSpecular(0.18)
                prop.SetSpecularPower(12.0)
            elif self.render_mode == "bone_mono":
                prop.SetAmbient(0.18)
                prop.SetDiffuse(0.72)
                prop.SetSpecular(0.30)
                prop.SetSpecularPower(25.0)
            else:
                prop.SetAmbient(0.10)
                prop.SetDiffuse(0.75)
                prop.SetSpecular(0.38)
                prop.SetSpecularPower(24.0)
        else:
            prop.ShadeOff()

    def _configure_vr_property_by_mode(self, prop: vtk.vtkVolumeProperty) -> None:
        if self.render_mode in ("cinematic", "spectral", "dual_volume", "exposure_render", "figure8_channels"):
            prop.ShadeOn()
            prop.SetAmbient(0.35)
            prop.SetDiffuse(0.85)
            prop.SetSpecular(0.35)
            prop.SetSpecularPower(40.0)
            base_dist = max(0.4, min(1.6, 0.5 + 2.0 * self.step_factor_shadow))
            dist = base_dist + getattr(self, 'cr_denoise', 0.0) * 0.8
            prop.SetScalarOpacityUnitDistance(dist)
            grad = vtk.vtkPiecewiseFunction()
            grad.AddPoint(0.0, 0.00)
            grad.AddPoint(5.0, 0.00)
            grad.AddPoint(25.0, 0.20)
            grad.AddPoint(60.0, 0.60)
            grad.AddPoint(120.0, 0.90)
            grad.AddPoint(200.0, 1.00)
            prop.SetGradientOpacity(grad)
        elif self.render_mode == "layer_channel":
            prop.ShadeOn()
            prop.SetAmbient(0.30)
            prop.SetDiffuse(0.88)
            prop.SetSpecular(0.12)
            prop.SetSpecularPower(8.0)
            base_dist = max(0.3, min(1.4, 0.4 + 2.0 * self.step_factor_shadow))
            dist = base_dist + getattr(self, 'cr_denoise', 0.0) * 0.6
            prop.SetScalarOpacityUnitDistance(dist)
            grad = vtk.vtkPiecewiseFunction()
            for x, y in self.gradient_opacity_points_layered:
                grad.AddPoint(float(x), float(y))
            prop.SetGradientOpacity(grad)
        elif self.render_mode == "frangi_channel":
            prop.ShadeOn()
            prop.SetAmbient(0.28)
            prop.SetDiffuse(0.90)
            prop.SetSpecular(0.10)
            prop.SetSpecularPower(8.0)
            base_dist = max(0.3, min(1.4, 0.4 + 2.0 * self.step_factor_shadow))
            dist = base_dist + getattr(self, 'cr_denoise', 0.0) * 0.5
            prop.SetScalarOpacityUnitDistance(dist)
            grad = vtk.vtkPiecewiseFunction()
            for x, y in self.gradient_opacity_points_frangi:
                grad.AddPoint(float(x), float(y))
            prop.SetGradientOpacity(grad)
        elif self.render_mode == "bone_mono":
            prop.ShadeOn()
            if self.cpu_render:
                prop.SetAmbient(0.15)
                prop.SetDiffuse(0.60)
                prop.SetSpecular(0.35)
                prop.SetSpecularPower(40.0)
            else:
                prop.SetAmbient(0.12)
                prop.SetDiffuse(0.55)
                prop.SetSpecular(0.85)
                prop.SetSpecularPower(120.0)
            base_dist = max(0.3, min(1.4, 0.4 + 2.0 * self.step_factor_shadow))
            dist = base_dist + getattr(self, 'cr_denoise', 0.0) * 0.5
            prop.SetScalarOpacityUnitDistance(dist)
            grad = vtk.vtkPiecewiseFunction()
            for x, y in self.gradient_opacity_points_bone_mono:
                grad.AddPoint(float(x), float(y))
            prop.SetGradientOpacity(grad)
        elif self.render_mode == "2dtf":
            prop.ShadeOn()
            prop.SetAmbient(0.15)
            prop.SetDiffuse(0.78)
            prop.SetSpecular(0.42)
            prop.SetSpecularPower(45.0)
            base_dist = max(0.3, min(1.4, 0.4 + 2.0 * self.step_factor_shadow))
            dist = base_dist + getattr(self, 'cr_denoise', 0.0) * 0.5
            prop.SetScalarOpacityUnitDistance(dist)
            grad = vtk.vtkPiecewiseFunction()
            grad.AddPoint(0.0, 1.0)
            grad.AddPoint(50.0, 1.0)
            prop.SetGradientOpacity(grad)
        elif self.render_mode == "nature_channels":
            prop.ShadeOn()
            prop.SetAmbient(0.20)
            prop.SetDiffuse(0.80)
            prop.SetSpecular(0.10)
            prop.SetSpecularPower(5.0)
        else:
            prop.ShadeOff()
            prop.SetScalarOpacityUnitDistance(1.0)

    def _apply_light_rig_for_mode(self) -> None:
        self.renderer.AutomaticLightCreationOff()
        self.renderer.RemoveAllLights()
        is_cr = self.render_mode in ("cinematic", "nature_channels", "spectral", "dual_volume", "exposure_render", "figure8_channels", "layer_channel", "frangi_channel")
        if is_cr:
            # 5-point light rig for even volume penetration + scattering
            # Key: front-right-above, primary illumination
            key = vtk.vtkLight()
            key.SetLightTypeToSceneLight()
            key.SetPositional(False)
            key.SetPosition(-0.7, -0.4, 1.0)
            key.SetFocalPoint(0.0, 0.0, 0.0)
            key.SetColor(1.00, 0.97, 0.93)
            key.SetIntensity(2.8)
            self.renderer.AddLight(key)

            # Fill: front-left, balances key shadows
            fill = vtk.vtkLight()
            fill.SetLightTypeToSceneLight()
            fill.SetPositional(False)
            fill.SetPosition(0.8, 0.2, 0.5)
            fill.SetFocalPoint(0.0, 0.0, 0.0)
            fill.SetColor(0.92, 0.94, 1.00)
            fill.SetIntensity(1.8)
            self.renderer.AddLight(fill)

            # Back: rear penetration / subsurface scattering simulation
            back = vtk.vtkLight()
            back.SetLightTypeToSceneLight()
            back.SetPositional(False)
            back.SetPosition(0.0, 0.0, -1.2)
            back.SetFocalPoint(0.0, 0.0, 0.0)
            back.SetColor(0.85, 0.90, 1.00)
            back.SetIntensity(1.6)
            self.renderer.AddLight(back)

            # Top rim: subtle highlight from above
            rim = vtk.vtkLight()
            rim.SetLightTypeToSceneLight()
            rim.SetPositional(False)
            rim.SetPosition(0.0, 1.1, 0.4)
            rim.SetFocalPoint(0.0, 0.0, 0.0)
            rim.SetColor(1.00, 0.96, 0.90)
            rim.SetIntensity(1.2)
            self.renderer.AddLight(rim)

            # Bottom fill: reduces harsh downward shadows
            bot = vtk.vtkLight()
            bot.SetLightTypeToSceneLight()
            bot.SetPositional(False)
            bot.SetPosition(0.0, -0.7, 0.0)
            bot.SetFocalPoint(0.0, 0.0, 0.0)
            bot.SetColor(0.88, 0.90, 0.95)
            bot.SetIntensity(0.8)
            self.renderer.AddLight(bot)
        else:
            # Non-CR: use same 5-point rig but at slightly reduced intensity for non-path-traced modes
            key = vtk.vtkLight()
            key.SetLightTypeToSceneLight()
            key.SetPositional(False)
            key.SetPosition(-0.7, -0.4, 1.0)
            key.SetFocalPoint(0.0, 0.0, 0.0)
            key.SetColor(1.00, 0.97, 0.93)
            key.SetIntensity(2.0 if self.render_mode in ("bone_mono", "2dtf") else 0.8)
            self.renderer.AddLight(key)
            fill = vtk.vtkLight()
            fill.SetLightTypeToSceneLight()
            fill.SetPositional(False)
            fill.SetPosition(0.8, 0.2, 0.5)
            fill.SetFocalPoint(0.0, 0.0, 0.0)
            fill.SetColor(0.92, 0.94, 1.00)
            fill.SetIntensity(1.2 if self.render_mode in ("bone_mono", "2dtf") else 0.30)
            self.renderer.AddLight(fill)
            back = vtk.vtkLight()
            back.SetLightTypeToSceneLight()
            back.SetPositional(False)
            back.SetPosition(0.0, 0.0, -1.2)
            back.SetFocalPoint(0.0, 0.0, 0.0)
            back.SetColor(0.85, 0.90, 1.00)
            back.SetIntensity(1.0 if self.render_mode in ("bone_mono", "2dtf") else 0.0)
            if self.render_mode in ("bone_mono", "2dtf"):
                self.renderer.AddLight(back)

    def get_original_ssd_points(self, mode):
        if mode == "stable":
            return self.ssd_opacity_points_stable
        elif mode == "hd_surface":
            return self.ssd_opacity_points_hd
        elif mode == "nature_channels":
            return self.ssd_opacity_points_nature
        elif mode in ("cinematic", "exposure_render"):
            return self.ssd_opacity_points_cinematic
        elif mode == "figure8_channels":
            return self.ssd_opacity_points_figure8
        elif mode == "layer_channel":
            return self.ssd_opacity_points_layered
        elif mode == "frangi_channel":
            return self.ssd_opacity_points_frangi
        elif mode == "bone_mono":
            return self.ssd_opacity_points_bone_mono
        elif mode == "2dtf":
            return [(-1000, 0.0), (3000, 0.0)]
        elif mode == "spectral":
            return self.ssd_opacity_points_hd
        return self.ssd_opacity_points_stable

    def on_ssd_threshold_change(self, lower, upper):
        self.ssd_threshold_label.setText(f"当前: [{lower},{upper}]")
        
        if self.render_mode == "dual_volume":
            self.ssd_opacity_points = [
                (-1000, 0.0),
                (lower - 1, 0.0),
                (lower, 0.8),
                (upper, 0.8),
                (upper + 1, 0.0),
                (3000, 0.0)
            ]
            color = self.ssd_color_points[1][1:] # get RGB
            self.ssd_color_points = [
                (-1000, 0.0, 0.0, 0.0),
                (lower, *color),
                (upper, *color),
                (3000, *color)
            ]
            self.on_slider_change(0)
            return
        
        orig_points = self.get_original_ssd_points(self.render_mode)
        if len(orig_points) < 3:
            return
            
        orig_lower = orig_points[1][0]
        orig_upper = orig_points[-2][0]
        
        new_points = []
        new_points.append(orig_points[0]) # (-1000, 0)
        
        for x, op in orig_points[1:-1]:
            if orig_upper == orig_lower:
                new_x = lower
            else:
                new_x = lower + (x - orig_lower) / (orig_upper - orig_lower) * (upper - lower)
            new_points.append((new_x, op))
            
        new_points.append((3000, orig_points[-1][1])) # (3000, max_op)
        
        self.ssd_opacity_points = new_points
        self.on_slider_change(0)

    def get_original_vr_points(self, mode):
        if mode == "nature_channels":
            return self.vr_opacity_points_nature
        elif mode == "figure8_channels":
            return self.vr_opacity_points_figure8
        elif mode == "layer_channel":
            return self.vr_opacity_points_layered
        elif mode == "frangi_channel":
            return self.vr_opacity_points_frangi
        elif mode == "bone_mono":
            if getattr(self, 'use_frangi', False):
                return self.vr_opacity_points_bone_mono_frangi
            return self.vr_opacity_points_bone_mono
        elif mode == "2dtf":
            return self.vr_opacity_points_2dtf
        elif mode in ("cinematic", "exposure_render"):
            return self.vr_opacity_points_cinematic
        elif mode == "spectral":
            return self.vr_opacity_points_spectral
        else:
            return [
                (-1000, 0.00),
                (10, 0.00),
                (20, 0.05),
                (80, 0.16),
                (120, 0.24),
                (150, 0.28),
                (180, 0.10),
                (260, 0.00),
            ]

    def toggle_background(self):
        self.bg_is_white = not self.bg_is_white
        if self.bg_is_white:
            self.renderer.SetBackground(0.88, 0.82, 0.84)  # Light wine
            self.seg_renderer.SetBackground(0.82, 0.76, 0.78)
            self.kedge_renderer.SetBackground(0.82, 0.76, 0.78)
        else:
            self.renderer.SetBackground(0.06, 0.02, 0.03)  # Deep wine red
            self.seg_renderer.SetBackground(0.04, 0.02, 0.03)
            self.kedge_renderer.SetBackground(0.04, 0.02, 0.03)

        if self.render_mode == "exposure_render":
            if self.er_wrapper:
                self.er_wrapper.reset_accumulation()

        self.render_window.Render()

    def on_preproc_change(self, value=None) -> None:
        self.denoise_method = "nlm" if self.check_nlm.isChecked() else "gaussian"
        self.use_clahe = self.check_clahe.isChecked()
        self.use_frangi = self.check_frangi.isChecked()
        self.use_distance_field = self.check_dist.isChecked() if hasattr(self, 'check_dist') else False
        self.use_2d_tf = self.check_2dtf.isChecked() if hasattr(self, 'check_2dtf') else False

    def on_vram_change(self, value: int) -> None:
        self.vram_threshold_gb = value

    def on_cpu_change(self, value=None) -> None:
        self.cpu_render = self.check_cpu.isChecked() if hasattr(self, 'check_cpu') else False

    def on_vr_threshold_change(self, lower=None, upper=None):
        if self.render_mode == "dual_volume":
            l1, u1 = self.vr_threshold_slider.value() if hasattr(self.vr_threshold_slider, 'value') else (self.vr_threshold_slider._lower, self.vr_threshold_slider._upper)
            l2, u2 = self.vr_threshold_slider2.value() if hasattr(self.vr_threshold_slider2, 'value') else (self.vr_threshold_slider2._lower, self.vr_threshold_slider2._upper)
            
            self.vr_threshold_label.setText(f"当前: [{int(l1)},{int(u1)}]")
            self.vr_threshold_label2.setText(f"当前: [{int(l2)},{int(u2)}]")
            
            # Rebuild VR TF with strictly two active regions
            self.vr_opacity_points = [
                (-1000, 0.0),
                (l2 - 1, 0.0), (l2, 0.6), (u2, 0.6), (u2 + 1, 0.0),
                (l1 - 1, 0.0), (l1, 0.6), (u1, 0.6), (u1 + 1, 0.0),
                (3000, 0.0)
            ]
            
            # Ensure points are sorted by HU
            self.vr_opacity_points.sort(key=lambda x: x[0])
            
            c1 = (0.10, 0.80, 0.80) # Cyan/Blue for VR Region 1
            c2 = (0.80, 0.20, 0.20) # Red for VR Region 2
            
            self.vr_color_points = [
                (-1000, 0.0, 0.0, 0.0),
                (l2, *c2), (u2, *c2),
                (l1, *c1), (u1, *c1),
                (3000, *c1)
            ]
            self.vr_color_points.sort(key=lambda x: x[0])
            
            self.on_slider_change(0)
            return

        if lower is None or upper is None:
            return
            
        self.vr_threshold_label.setText(f"当前: [{lower},{upper}]")
        
        orig_points = self.get_original_vr_points(self.render_mode)
        if len(orig_points) < 3:
            return
            
        orig_lower = orig_points[1][0]
        orig_upper = orig_points[-2][0]
        
        new_points = []
        new_points.append(orig_points[0]) # (-1000, 0)
        
        for x, op in orig_points[1:-1]:
            if orig_upper == orig_lower:
                new_x = lower
            else:
                new_x = lower + (x - orig_lower) / (orig_upper - orig_lower) * (upper - lower)
            new_points.append((new_x, op))
            
        new_points.append((3000, orig_points[-1][1])) # (3000, max_op)
        
        self.vr_opacity_points = new_points
        self.on_slider_change(0)

    def _er_render_step(self):
        if not self.er_wrapper or self.render_mode != "exposure_render":
            return
            
        tracer_id = self.er_wrapper.get_tracer_id()
        self.er_wrapper.render_estimate(tracer_id)
        
        # Get frame estimate back
        if self.er_buffer is not None:
            self.er_wrapper.get_estimate(tracer_id, self.er_buffer.ctypes.data_as(ctypes.c_void_p))
            
            # RGBA format update
            import vtkmodules.util.numpy_support as vtk_np
            vtk_array = vtk_np.numpy_to_vtk(num_array=self.er_buffer.ravel(), deep=False, array_type=vtk.VTK_UNSIGNED_CHAR)
            self.er_image_data.GetPointData().SetScalars(vtk_array)
            self.er_image_data.Modified()
            self.render_window.Render()
            
        # Instead of continuous repeating timer, we schedule the next frame to allow Qt event loop to process events
        if self.render_mode == "exposure_render":
            QtCore.QTimer.singleShot(1, self._er_render_step)

    def on_preset_change(self, index: int) -> None:
        preset_name = self.preset_combo.currentText()
        if preset_name == "None (使用滑块调节)":
            self.on_mode_change(self.mode_combo.combo_box().currentIndex())
            return
            
        if preset_name in self.slicer_presets:
            preset = self.slicer_presets[preset_name]
            
            # Apply Opacity
            if preset['opacity']:
                self.vr_opacity_points = preset['opacity']
            
            # Apply Color
            if preset['color']:
                self.vr_color_points = preset['color']
                
            # Apply Lighting Properties
            if self.current_vr_volume is not None:
                prop = self.current_vr_volume.GetProperty()
                prop.SetAmbient(preset['ambient'])
                prop.SetDiffuse(preset['diffuse'])
                prop.SetSpecular(preset['specular'])
                prop.SetSpecularPower(preset['specularPower'])
                
            if self.render_mode == "exposure_render" and self.er_wrapper:
                self.er_wrapper.update_opacity_tf(self.vr_opacity_points)
                self.er_wrapper.update_diffuse_tf(self.vr_color_points)
                self.er_wrapper.reset_accumulation()
            else:
                if self.current_vr_volume is not None:
                    self.current_vr_volume.GetProperty().SetScalarOpacity(make_opacity(self.vr_opacity_points))
                    self.current_vr_volume.GetProperty().SetColor(make_color(self.vr_color_points))
            
            self.render_window.Render()

    def on_mode_change(self, index: int) -> None:
        if index == 11:
            self.render_mode = "dual_volume"
        elif index == 10:
            self.render_mode = "exposure_render"
        elif index == 9:
            self.render_mode = "spectral"
        elif index == 8:
            self.render_mode = "2dtf"
        elif index == 7:
            self.render_mode = "bone_mono"
        elif index == 6:
            self.render_mode = "frangi_channel"
        elif index == 5:
            self.render_mode = "layer_channel"
        elif index == 4:
            self.render_mode = "figure8_channels"
        elif index == 3:
            self.render_mode = "nature_channels"
        elif index == 2:
            self.render_mode = "cinematic"
        elif index == 1:
            self.render_mode = "hd_surface"
        else:
            self.render_mode = "stable"

        # Ensure UI updates match mode requirements
        if hasattr(self, "cr_widget"):
            if self.render_mode in ("cinematic", "nature_channels", "spectral", "exposure_render", "dual_volume", "figure8_channels", "layer_channel", "frangi_channel"):
                self.cr_widget.show()
            else:
                self.cr_widget.hide()

        if self.render_mode == "exposure_render":
            if self.er_image_actor:
                self.er_image_actor.SetVisibility(True)
            if self.current_vr_volume:
                self.current_vr_volume.SetVisibility(False)
            if self.current_ssd_volume:
                self.current_ssd_volume.SetVisibility(False)
            # Start the render loop if not already running
            QtCore.QTimer.singleShot(1, self._er_render_step)
        else:
            if self.er_image_actor:
                self.er_image_actor.SetVisibility(False)
            if self.current_vr_volume:
                self.current_vr_volume.SetVisibility(True)
            if self.current_ssd_volume:
                self.current_ssd_volume.SetVisibility(True)

        if self.render_mode == "dual_volume":
            self.vr_threshold_slider2.show()
            self.vr_threshold_label2.show()
            self.ssd_threshold_slider.hide()
            self.ssd_threshold_label.hide()
            
            self.ssd_opacity_points = [
                (-1000, 0.0), (3000, 0.0) # Hide SSD entirely
            ]
            self.ssd_color_points = [
                (-1000, 0.0, 0.0, 0.0), (3000, 0.0, 0.0, 0.0)
            ]
            self.vr_opacity_points = [
                (-1000, 0.0), (-201, 0.0), (-200, 0.6), (-50, 0.6), (-49, 0.0),
                (49, 0.0), (50, 0.6), (200, 0.6), (201, 0.0), (3000, 0.0)
            ]
            self.vr_color_points = [
                (-1000, 0.0, 0.0, 0.0),
                (-200, 0.80, 0.20, 0.20), # Red
                (-50, 0.80, 0.20, 0.20),
                (50, 0.10, 0.80, 0.80),   # Cyan / Blue
                (200, 0.10, 0.80, 0.80),
                (3000, 0.10, 0.80, 0.80),
            ]
        elif self.render_mode == "hd_surface":
            self.vr_threshold_slider2.hide()
            self.vr_threshold_label2.hide()
            self.ssd_threshold_slider.show()
            self.ssd_threshold_label.show()
            self.ssd_opacity_points = list(self.ssd_opacity_points_hd)
            self.ssd_color_points = list(self.ssd_color_points_stable)
        elif self.render_mode == "nature_channels":
            self.vr_threshold_slider2.hide()
            self.vr_threshold_label2.hide()
            self.ssd_threshold_slider.show()
            self.ssd_threshold_label.show()
            self.ssd_opacity_points = list(self.ssd_opacity_points_nature)
            self.ssd_color_points = list(self.ssd_color_points_stable)
            self.vr_opacity_points = list(self.vr_opacity_points_nature)        
            self.vr_color_points = list(self.vr_color_points_nature)
        elif self.render_mode == "figure8_channels":
            self.vr_threshold_slider2.hide()
            self.vr_threshold_label2.hide()
            self.ssd_threshold_slider.show()
            self.ssd_threshold_label.show()
            self.ssd_opacity_points = list(self.ssd_opacity_points_figure8)
            self.ssd_color_points = list(self.ssd_color_points_figure8)
            self.vr_opacity_points = list(self.vr_opacity_points_figure8)
            self.vr_color_points = list(self.vr_color_points_figure8)
            if self.vr_slider.slider().value() < 55:
                self.vr_slider.slider().setValue(70)
        elif self.render_mode == "layer_channel":
            self.vr_threshold_slider2.hide()
            self.vr_threshold_label2.hide()
            self.ssd_threshold_slider.show()
            self.ssd_threshold_label.show()
            self.ssd_opacity_points = list(self.ssd_opacity_points_layered)
            self.ssd_color_points = list(self.ssd_color_points_layered)
            self.vr_opacity_points = list(self.vr_opacity_points_layered)
            self.vr_color_points = list(self.vr_color_points_layered)
            if self.vr_slider.slider().value() < 55:
                self.vr_slider.slider().setValue(70)
        elif self.render_mode == "frangi_channel":
            self.vr_threshold_slider2.hide()
            self.vr_threshold_label2.hide()
            self.ssd_threshold_slider.show()
            self.ssd_threshold_label.show()
            self.ssd_opacity_points = list(self.ssd_opacity_points_frangi)
            self.ssd_color_points = list(self.ssd_color_points_frangi)
            self.vr_opacity_points = list(self.vr_opacity_points_frangi)
            self.vr_color_points = list(self.vr_color_points_frangi)
            if self.vr_slider.slider().value() < 55:
                self.vr_slider.slider().setValue(70)
            if hasattr(self, 'check_frangi'):
                self.check_frangi.blockSignals(True)
                self.check_frangi.setChecked(True)
                self.check_frangi.blockSignals(False)
            if hasattr(self, 'check_nlm'):
                self.check_nlm.blockSignals(True)
                self.check_nlm.setChecked(True)
                self.check_nlm.blockSignals(False)
            self.on_preproc_change()
        elif self.render_mode == "bone_mono":
            self.vr_threshold_slider2.hide()
            self.vr_threshold_label2.hide()
            self.ssd_threshold_slider.hide()
            self.ssd_threshold_label.hide()
            self.ssd_opacity_points = [(-1000, 0.0), (3000, 0.0)]
            self.ssd_color_points = [(-1000, 0.0, 0.0, 0.0), (3000, 0.0, 0.0, 0.0)]
            self.on_preproc_change()
            self.use_2d_tf = False
            self.use_2d_tf_bone = False
            if self.use_frangi:
                self.vr_opacity_points = sorted(self.vr_opacity_points_bone_mono_frangi)
                self.vr_color_points = sorted(self.vr_color_points_bone_mono_frangi)
            else:
                self.vr_opacity_points = list(self.vr_opacity_points_bone_mono)
                self.vr_color_points = list(self.vr_color_points_bone_mono)
            if self.vr_slider.slider().value() < 55:
                self.vr_slider.slider().setValue(70)
        elif self.render_mode == "2dtf":
            self.vr_threshold_slider2.hide()
            self.vr_threshold_label2.hide()
            self.ssd_threshold_slider.hide()
            self.ssd_threshold_label.hide()
            self.ssd_opacity_points = [(-1000, 0.0), (3000, 0.0)]
            self.ssd_color_points = [(-1000, 0.0, 0.0, 0.0), (3000, 0.0, 0.0, 0.0)]
            if hasattr(self, 'check_2dtf'):
                self.check_2dtf.blockSignals(True)
                self.check_2dtf.setChecked(True)
                self.check_2dtf.blockSignals(False)
            self.on_preproc_change()
            import sys
            print(f"[2dtf] 2D TF 预处理将运行, 预计 3-5 分钟...")
            sys.stdout.flush()
            self.vr_opacity_points = list(self.vr_opacity_points_2dtf)
            self.vr_color_points = list(self.vr_color_points_2dtf)
            if self.vr_slider.slider().value() < 55:
                self.vr_slider.slider().setValue(70)
        elif self.render_mode in ("cinematic", "exposure_render"):
            self.vr_threshold_slider2.hide()
            self.vr_threshold_label2.hide()
            self.ssd_threshold_slider.show()
            self.ssd_threshold_label.show()
            self.ssd_opacity_points = list(self.ssd_opacity_points_cinematic)
            self.ssd_color_points = list(self.ssd_color_points_cinematic)
            self.vr_opacity_points = list(self.vr_opacity_points_cinematic)     
            self.vr_color_points = list(self.vr_color_points_cinematic)
            if self.vr_slider.slider().value() < 55:
                self.vr_slider.slider().setValue(75)
        elif self.render_mode == "spectral":
            self.vr_threshold_slider2.hide()
            self.vr_threshold_label2.hide()
            self.ssd_threshold_slider.show()
            self.ssd_threshold_label.show()
            self.ssd_opacity_points = list(self.ssd_opacity_points_hd)
            self.ssd_color_points = list(self.ssd_color_points_stable)
            self.vr_opacity_points = list(self.vr_opacity_points_spectral)     
            self.vr_color_points = list(self.vr_color_points_spectral)
            if self.vr_slider.slider().value() < 55:
                self.vr_slider.slider().setValue(75)
        else:
            self.vr_threshold_slider2.show()
            self.vr_threshold_label2.show()
            self.ssd_threshold_slider.show()
            self.ssd_threshold_label.show()
            self.ssd_opacity_points = list(self.ssd_opacity_points_stable)
            self.ssd_color_points = list(self.ssd_color_points_stable)
            self.vr_opacity_points = [
                (-1000, 0.00),
                (10, 0.00),
                (20, 0.05),
                (80, 0.16),
                (120, 0.24),
                (150, 0.28),
                (180, 0.10),
                (260, 0.00),
            ]
            self.vr_color_points = [
                (-1000, 0.00, 0.00, 0.00),
                (20, 0.55, 0.18, 0.18),
                (80, 0.72, 0.30, 0.28),
                (120, 0.82, 0.42, 0.36),
                (150, 0.92, 0.56, 0.46),
                (260, 0.95, 0.80, 0.70),
            ]

        # Initialize the range slider values dynamically based on mode
        orig_points = self.get_original_ssd_points(self.render_mode)
        if len(orig_points) >= 3:
            orig_lower = orig_points[1][0] if self.render_mode != "dual_volume" else 300
            orig_upper = orig_points[-2][0] if self.render_mode != "dual_volume" else 1500
            self.ssd_threshold_slider.blockSignals(True)
            self.ssd_threshold_slider.setValues(orig_lower, orig_upper)
            self.ssd_threshold_label.setText(f"当前: [{orig_lower}, {orig_upper}]")
            self.ssd_threshold_slider.blockSignals(False)

        orig_vr_points = self.get_original_vr_points(self.render_mode)
        if len(orig_vr_points) >= 3:
            orig_lower_vr = orig_vr_points[1][0] if self.render_mode != "dual_volume" else 50
            orig_upper_vr = orig_vr_points[-2][0] if self.render_mode != "dual_volume" else 200
            self.vr_threshold_slider.blockSignals(True)
            self.vr_threshold_slider.setValues(orig_lower_vr, orig_upper_vr)
            self.vr_threshold_label.setText(f"当前: [{orig_lower_vr}, {orig_upper_vr}]")
            self.vr_threshold_slider.blockSignals(False)

        if self.controller is not None:
            # Different modes correspond to different mapper pipelines, rebuild is most reliable
            self.load_dicom()
            return

        if self.current_ssd_volume is not None:
            ssd_prop = self.current_ssd_volume.GetProperty()
            self._configure_ssd_property_by_mode(ssd_prop)
            ssd_prop.SetScalarOpacity(
                make_opacity(self.ssd_opacity_points, self.ssd_slider.slider().value() / 100.0)
            )

        if self.current_vr_volume is not None:
            vr_prop = self.current_vr_volume.GetProperty()
            vr_prop.SetColor(make_color(self.vr_color_points))
            vr_prop.SetScalarOpacity(
                make_opacity(self.vr_opacity_points, self.vr_slider.slider().value() / 100.0)
            )
            self._configure_vr_property_by_mode(vr_prop)

        if self.controller is not None:
            self.controller.ssd_points = self.ssd_opacity_points
            self.controller.vr_points = self.vr_opacity_points
            self.controller.ssd_color_points = self.ssd_color_points
            self.controller.vr_color_points = self.vr_color_points
            self.controller.update(
                self._effective_ssd_scale(self.ssd_slider.slider().value() / 100.0),
                self._effective_vr_scale(self.vr_slider.slider().value() / 100.0),
                self.er_exposure,
            )

        self._apply_light_rig_for_mode()
        self._apply_cr_runtime_params()
        self.render_window.Render()

    def on_crop_toggle(self, checked: bool) -> None:
        if self.box_widget is not None:
            if checked:
                # 仅控制裁剪框可见性，不改变当前裁剪结果
                self.box_widget.On()
            else:
                # 仅控制裁剪框可见性，不改变当前裁剪结果
                self.box_widget.Off()
            self.render_window.Render()

    def _box_bounds(self, box_widget: vtk.vtkBoxWidget) -> Tuple[float, float, float, float, float, float]:
        pd = vtk.vtkPolyData()
        box_widget.GetPolyData(pd)
        return pd.GetBounds()

    def _apply_crop_to_active_mappers(
        self, bounds: Tuple[float, float, float, float, float, float]
    ) -> None:
        if hasattr(self, "current_vr_mapper") and self.current_vr_mapper is not None:
            self.current_vr_mapper.SetCroppingRegionFlagsToSubVolume()
            self.current_vr_mapper.SetCropping(True)
            self.current_vr_mapper.SetCroppingRegionPlanes(bounds)
        if hasattr(self, "current_ssd_mapper") and self.current_ssd_mapper is not None:
            self.current_ssd_mapper.SetCroppingRegionFlagsToSubVolume()
            self.current_ssd_mapper.SetCropping(True)
            self.current_ssd_mapper.SetCroppingRegionPlanes(bounds)

    def set_progress(self, percent: int, message: str) -> None:
        value = max(0, min(100, int(percent)))
        self.progress_bar.setValue(value)
        self.progress_text.append(message)
        QtWidgets.QApplication.processEvents()

    def _clear_old_volumes(self) -> None:
        if self.box_widget is not None:
            self.box_widget.Off()
            self.box_widget = None
        self.current_vr_mapper = None
        self.current_ssd_mapper = None

        if hasattr(self, 'current_multi_volume') and self.current_multi_volume is not None:
            self.renderer.RemoveVolume(self.current_multi_volume)
            self.current_multi_volume = None
        if self.current_vr_volume is not None:
            self.renderer.RemoveVolume(self.current_vr_volume)
            self.current_vr_volume = None
        if self.current_ssd_volume is not None:
            self.renderer.RemoveVolume(self.current_ssd_volume)
            self.current_ssd_volume = None
        self.controller = None

    def load_dicom(self) -> None:
        dicom_path = self.path_edit.line_edit().text().strip()
        if not dicom_path or not os.path.exists(dicom_path):
            QtWidgets.QMessageBox.warning(self, "路径无效", "请输入有效的 DICOM 路径。")
            return

        self.btn_load.setEnabled(False)
        self.progress_text.clear()
        self.set_progress(0, "开始加载 DICOM (SimpleITK) ...")
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        QtWidgets.QApplication.processEvents()

        try:
            if self.use_2d_tf or self.use_2d_tf_bone:
                print(f"[2D TF] build_reader flags: use_2d_tf={self.use_2d_tf}, use_2d_tf_bone={self.use_2d_tf_bone}, denoise={self.denoise_method}")
                import sys; sys.stdout.flush()
            image_data, downsample_msg = build_reader(dicom_path, self.denoise_method, self.use_clahe, self.use_frangi, self.use_distance_field, self.use_2d_tf, self.use_2d_tf_bone, self.vram_threshold_gb, self.cpu_render)
            self.set_progress(35, "DICOM 数据读取完成。")
            if downsample_msg:
                self.set_progress(40, downsample_msg)

            if image_data is None or image_data.GetDimensions() == (0, 0, 0):
                raise RuntimeError("无法提取有效的体数据。")
            dims = image_data.GetDimensions()
            self.image_data = image_data
            self.set_progress(45, f"体数据尺寸: {dims[0]} x {dims[1]} x {dims[2]}")

            try:
                if os.path.isdir(dicom_path):
                    reader = sitk.ImageSeriesReader()
                    reader.SetFileNames(reader.GetGDCMSeriesFileNames(dicom_path))
                    self.original_sitk_image = reader.Execute()
                else:
                    self.original_sitk_image = sitk.ReadImage(dicom_path)
            except Exception as e:
                print(f"Warning: Failed to store original sitk image: {e}")
                self.original_sitk_image = None

            if er_core is not None:
                self.set_progress(50, "初始化 Exposure Render (CUDA) 核心...")
                try:
                    if self.er_wrapper is None:
                        self.er_wrapper = ErCoreWrapper()
                    
                    # Convert VTK image data pointer to ctypes void pointer
                    import vtkmodules.util.numpy_support as vtk_np
                    vtk_array = image_data.GetPointData().GetScalars()
                    np_array = vtk_np.vtk_to_numpy(vtk_array)
                    
                    dims = image_data.GetDimensions()
                    spacing = image_data.GetSpacing()
                    
                    # ErCore assumes unsigned short. VTK DICOM is usually int16.
                    # We shift by 32768 to map int16 range to uint16 safely.
                    np_array = (np_array.astype(np.int32) + 32768).astype(np.uint16)
                    
                    # Keep reference to prevent GC
                    self._er_data_ref = np_array
                    
                    self.er_wrapper.bind_volume_data(dims, spacing, self._er_data_ref.ctypes.data_as(ctypes.c_void_p))
                except Exception as e:
                    print(f"Failed to initialize Exposure Render: {e}")

            self.set_progress(55, "初始化稳定渲染 mapper ...")
            
            # 使用 vtkTrivialProducer 将 vtkImageData 接入到 Pipeline
            self.producer = vtk.vtkTrivialProducer()
            self.producer.SetOutput(image_data)
            
            # Use vtkGPUVolumeRayCastMapper as the primary engine for standard modes
            use_path_tracing = self.render_mode in ("cinematic", "nature_channels", "spectral", "dual_volume", "figure8_channels", "layer_channel", "frangi_channel")
            
            if use_path_tracing:
                mapper_cls = vtk.vtkSmartVolumeMapper
            elif self.render_mode == "hd_surface":
                mapper_cls = vtk.vtkGPUVolumeRayCastMapper
            else:
                mapper_cls = vtk.vtkGPUVolumeRayCastMapper

            if self.cpu_render:
                mapper_cls = vtk.vtkFixedPointVolumeRayCastMapper
                print("[CPU Render] 使用 vtkFixedPointVolumeRayCastMapper (系统 RAM)，无下采样全分辨率")

            # CR uses a single combined volume. Others use dual mappers.
            ssd_mapper = mapper_cls()
            ssd_mapper.SetInputConnection(self.producer.GetOutputPort())        
            ssd_mapper.SetBlendModeToComposite()
            
            # Apply GPU memory constraints (70% of user-set VRAM threshold) to avoid overflow
            gpu_budget = int(self.vram_threshold_gb * 0.7 * 1024 * 1024 * 1024)
            if not use_path_tracing and not self.cpu_render and hasattr(ssd_mapper, "SetMaxMemoryInBytes"):
                ssd_mapper.SetMaxMemoryInBytes(gpu_budget)
            if not use_path_tracing and hasattr(ssd_mapper, "SetMaxMemoryFraction"):
                ssd_mapper.SetMaxMemoryFraction(0.65)
                
            if use_path_tracing:
                ssd_mapper.SetSampleDistance(self._path_tracing_sample_distance())
                if hasattr(ssd_mapper, "SetVolumetricScatteringBlending"):
                    ssd_mapper.SetVolumetricScatteringBlending(self.scatter_blend)
                if hasattr(ssd_mapper, "SetMaxMemoryInBytes"):
                    ssd_mapper.SetMaxMemoryInBytes(gpu_budget)
                if hasattr(ssd_mapper, "SetMaxMemoryFraction"):
                    ssd_mapper.SetMaxMemoryFraction(0.65)
            else:
                ssd_mapper.SetSampleDistance(1.2)

            vr_mapper = ssd_mapper if use_path_tracing else mapper_cls()    
            if not use_path_tracing:
                vr_mapper.SetInputConnection(self.producer.GetOutputPort()) 
                vr_mapper.SetBlendModeToComposite()
                vr_mapper.SetSampleDistance(1.2)
                if not self.cpu_render:
                    if hasattr(vr_mapper, "SetMaxMemoryInBytes"):
                        vr_mapper.SetMaxMemoryInBytes(gpu_budget)
                    if hasattr(vr_mapper, "SetMaxMemoryFraction"):
                        vr_mapper.SetMaxMemoryFraction(0.65)
            if self.cpu_render and hasattr(ssd_mapper, "SetFixedPointBlockSize"):
                ssd_mapper.SetFixedPointBlockSize(128)
                if vr_mapper is not ssd_mapper:
                    vr_mapper.SetFixedPointBlockSize(128)
            
            # --- 确保初始裁剪状态开启 ---
            is_crop_checked = self.check_crop.isChecked()
            ssd_mapper.SetCropping(True)
            if vr_mapper is not ssd_mapper:
                vr_mapper.SetCropping(True)
            
            if self.cpu_render:
                self.set_progress(65, f"CPU 全分辨率渲染 (vtkFixedPointVolumeRayCastMapper, {self.vram_threshold_gb}GB VRAM)。")
            elif use_path_tracing:
                self.set_progress(65, "CR 路径追踪渲染器已就绪（混合散射）。")
            else:
                self.set_progress(65, f"采用 GPU 混合模式：已启用 vtkGPUVolumeRayCastMapper (显存限额 {self.vram_threshold_gb}GB)。")

            ssd_prop = vtk.vtkVolumeProperty()
            ssd_prop.SetColor(make_color(self.ssd_color_points))
            ssd_prop.SetScalarOpacity(make_opacity(self.ssd_opacity_points, 0.9))
            ssd_prop.SetInterpolationTypeToLinear()
            self._configure_ssd_property_by_mode(ssd_prop)

            vr_prop = vtk.vtkVolumeProperty()
            vr_prop.SetColor(make_color(self.vr_color_points))
            vr_prop.SetScalarOpacity(make_opacity(self.vr_opacity_points, 0.9))
            vr_prop.SetInterpolationTypeToLinear()
            self._configure_vr_property_by_mode(vr_prop)
            vr_prop.SetScatteringAnisotropy(self.scatter_g)
            ssd_prop.SetScatteringAnisotropy(min(0.95, self.scatter_g * 0.8))

            if use_path_tracing:
                fused_prop = vtk.vtkVolumeProperty()
                fused_prop.SetInterpolationTypeToLinear()
                self._configure_vr_property_by_mode(fused_prop)
                fused_prop.SetScatteringAnisotropy(self.scatter_g)
                fused_volume = vtk.vtkVolume()
                fused_volume.SetMapper(ssd_mapper)
                fused_volume.SetProperty(fused_prop)
                ssd_volume = None
                vr_volume = fused_volume
            else:
                ssd_volume = vtk.vtkVolume()
                ssd_volume.SetMapper(ssd_mapper)
                ssd_volume.SetProperty(ssd_prop)

                vr_volume = vtk.vtkVolume()
                vr_volume.SetMapper(vr_mapper)
                vr_volume.SetProperty(vr_prop)

            self._clear_old_volumes()
            
            # Setup VTK Image Actor for Exposure Render
            if self.er_image_actor is None:
                w, h = self.render_window.GetSize()
                if w == 0 or h == 0:
                    w, h = 800, 600
                    
                self.er_buffer = np.zeros((h, w, 4), dtype=np.uint8)
                
                # Create VTK Image Data mapped to numpy array
                import vtkmodules.util.numpy_support as vtk_np
                self.er_image_data = vtk.vtkImageData()
                self.er_image_data.SetDimensions(w, h, 1)
                self.er_image_data.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 4)
                vtk_array = vtk_np.numpy_to_vtk(num_array=self.er_buffer.ravel(), deep=False, array_type=vtk.VTK_UNSIGNED_CHAR)
                self.er_image_data.GetPointData().SetScalars(vtk_array)
                
                self.er_image_actor = vtk.vtkImageActor()
                self.er_image_actor.SetInputData(self.er_image_data)
                self.renderer.AddActor(self.er_image_actor)
                
                # Make sure actor covers the background
                self.er_image_actor.SetVisibility(False)
                
            self.current_vr_mapper = vr_mapper
            self.current_ssd_mapper = ssd_mapper
            self.current_vr_volume = vr_volume
            self.current_ssd_volume = ssd_volume
            
            if vr_volume is not None:
                self.renderer.AddVolume(vr_volume)
            if ssd_volume is not None:
                self.renderer.AddVolume(ssd_volume)
            self._apply_light_rig_for_mode()
            
            # --- 增加 vtkBoxWidget 裁剪功能 ---
            self.box_widget = vtk.vtkBoxWidget()
            self.box_widget.SetInteractor(self.iren)
            self.box_widget.SetPlaceFactor(1.0)
            self.box_widget.SetInputData(image_data)
            self.box_widget.PlaceWidget()
            self.box_widget.InsideOutOn()
            self.box_widget.SetRotationEnabled(0) # 保持轴对齐，以匹配 CroppingRegionPlanes
            
            # --- 设置初始裁剪范围 ---
            init_bounds = self._box_bounds(self.box_widget)
            if is_crop_checked:
                self._apply_crop_to_active_mappers(init_bounds)

            # 优化线框外观：使其仅作为一个交互控制器，避免遮挡渲染内容
            outline_prop = self.box_widget.GetOutlineProperty()
            outline_prop.SetColor(1.0, 1.0, 0.0) # 黄色边框
            
            face_prop = self.box_widget.GetFaceProperty()
            face_prop.SetOpacity(0.0) # 面完全透明
            
            selected_face_prop = self.box_widget.GetSelectedFaceProperty()
            selected_face_prop.SetOpacity(0.3) # 选中面半透明
            selected_face_prop.SetColor(1.0, 1.0, 0.0)

            def on_box_interaction(obj, event):
                self._apply_crop_to_active_mappers(self._box_bounds(obj))
                # 必须显式触发重新渲染，否则拖动时不会实时更新
                self.render_window.Render()
                
            self.box_widget.AddObserver("InteractionEvent", on_box_interaction)
            # 初始化即生效裁剪；checkbox 只控制框体显示/隐藏
            self._apply_crop_to_active_mappers(init_bounds)
            if self.check_crop.isChecked():
                self.box_widget.On()
            else:
                self.box_widget.Off()
            
            if use_path_tracing:
                self.set_progress(80, "已完成 CR 单体积 Monte Carlo 挂载（SSD/VR 分类融合）。")
            else:
                self.set_progress(80, "已完成 SSD+VR 独立容积裁剪挂载。")

            self.controller = FusionController(
                ssd_volume,
                vr_volume,
                self.ssd_opacity_points,
                self.vr_opacity_points,
                self.ssd_color_points,
                self.vr_color_points,
                fused_volume=vr_volume if use_path_tracing else None,
            )
            
            # Apply sliders and window level offsets to ensure correct initialization
            self.on_slider_change(0)

            self.renderer.ResetCamera()
            cam = self.renderer.GetActiveCamera()
            fp = cam.GetFocalPoint()
            pos = cam.GetPosition()
            distance = ((pos[0] - fp[0]) ** 2 + (pos[1] - fp[1]) ** 2 + (pos[2] - fp[2]) ** 2) ** 0.5
            # Start from a coronal-like viewpoint to mirror Figure 8 style.
            cam.SetPosition(fp[0], fp[1] - max(distance, 1.0), fp[2])
            cam.SetViewUp(0, 0, 1)
            self.renderer.ResetCameraClippingRange()
            self._apply_cr_runtime_params()
            self.render_window.Render()
            self.set_progress(100, "渲染完成。可交互浏览。")

            self.statusBar().showMessage(
                "左键：旋转 | 中键/Shift+左键：平移 | 右键：缩放 | 拖动裁剪框：实时剪裁。 SSD/VR 参数可独立调节。"
            )
        except Exception as exc:
            import traceback
            traceback.print_exc()
            QtWidgets.QMessageBox.critical(self, "加载失败", f"DICOM 加载或渲染失败：\n{exc}")
            self.set_progress(0, "加载失败。")
        finally:
            self.btn_load.setEnabled(True)
            QtWidgets.QApplication.restoreOverrideCursor()

    def on_seg_start(self):
        if self.original_sitk_image is None:
            QtWidgets.QMessageBox.warning(self, "无数据", "请先在渲染页面加载DICOM数据。")
            return
        self._do_segmentation()

    def on_seg_cancel(self):
        if self.seg_pipeline and self.seg_pipeline.isRunning():
            self.seg_pipeline.cancel()
            self.seg_progress_label.setText("正在取消...")
            self.seg_btn_cancel.setEnabled(False)

    def on_seg_clear(self):
        if self.seg_visualizer:
            self.seg_visualizer.remove_all()
        if self.right_volume:
            self.seg_renderer.RemoveVolume(self.right_volume)
            self.right_volume = None
            self.right_producer = None
            self.right_mapper = None
        self.seg_result = None
        self.seg_stats_group.setVisible(False)
        self.seg_btn_clear.setEnabled(False)
        self.seg_progress_bar.setValue(0)
        self.seg_progress_label.setText("就绪")
        self.iren.Render()

    def _do_segmentation(self):
        spacing_text = self.seg_spacing_combo.currentText()
        if spacing_text == "不移采样":
            spacing = None
        else:
            sp = float(spacing_text.split()[0])
            spacing = (sp, sp, sp)

        hu_low = self.seg_hu_low.value()
        hu_high = self.seg_hu_high.value()
        min_comp = self.seg_cc_size.value() if self.seg_check_cc.isChecked() else 0
        close_k = self.seg_close_kernel.value() if self.seg_check_close.isChecked() else 1
        clicks = self.seg_clicks.value()
        threshold = self.seg_threshold.value()

        self.seg_btn_start.setEnabled(False)
        self.seg_btn_cancel.setEnabled(True)
        self.seg_btn_clear.setEnabled(False)
        self.seg_progress_bar.setValue(0)
        self.seg_progress_label.setText("准备中...")

        self.seg_pipeline = SegmentationPipeline(
            sitk_image=self.original_sitk_image,
            hu_window=(hu_low, hu_high),
            target_spacing=spacing or self.original_sitk_image.GetSpacing(),
            use_sam=True,
            use_nnunet=False,
            num_clicks=clicks,
            threshold=threshold,
            min_component_size=min_comp,
            closing_kernel=close_k,
        )
        self.seg_pipeline.progress_signal.connect(self._on_seg_progress)
        self.seg_pipeline.finished_signal.connect(self._on_seg_finished)
        self.seg_pipeline.error_signal.connect(self._on_seg_error)
        self.seg_pipeline.start()

    def _on_seg_progress(self, percent, message):
        self.seg_progress_bar.setValue(percent)
        self.seg_progress_label.setText(message)

    def _on_seg_finished(self, result):
        self.seg_btn_start.setEnabled(True)
        self.seg_btn_cancel.setEnabled(False)
        self.seg_btn_clear.setEnabled(True)
        self.seg_result = result

        stats = result["stats"]
        stats_text = (
            f"总血管体积: {stats['volume_cm3']:.1f} cm³ | "
            f"体素: {stats['total_voxels']:,} | "
            f"连通域: {stats['num_components']} | "
            f"最大域: {stats['largest_component']:,}"
        )
        self.seg_stats_label.setText(stats_text)
        self.seg_stats_group.setVisible(True)

        if self.seg_visualizer is None:
            self.seg_visualizer = SegmentationVisualizer(self.renderer)

        if self.seg_check_surface.isChecked():
            self.seg_visualizer.add_vessel_surface(
                result["mask"], result["spacing"], result["origin"]
            )
        elif self.seg_check_volume.isChecked():
            self.seg_visualizer.add_vessel_volume(
                result["mask"], result["spacing"], result["origin"]
            )
        else:
            self.seg_visualizer.add_vessel_surface(
                result["mask"], result["spacing"], result["origin"]
            )

        self.seg_progress_label.setText("分割完成")

        if self.image_data is not None and result["mask"].sum() > 0:
            self._render_right_masked_ct(result)

        self.iren.Render()

    def _on_seg_error(self, error_msg):
        self.seg_btn_start.setEnabled(True)
        self.seg_btn_cancel.setEnabled(False)
        self.seg_progress_label.setText(f"错误: {error_msg}")
        QtWidgets.QMessageBox.critical(self, "分割失败", error_msg)

    def _on_seg_vis_change(self):
        if self.seg_result is None or self.seg_visualizer is None:
            return
        self.seg_visualizer.remove_all()
        if self.seg_check_surface.isChecked():
            self.seg_visualizer.add_vessel_surface(
                self.seg_result["mask"],
                self.seg_result["spacing"],
                self.seg_result["origin"],
            )
        elif self.seg_check_volume.isChecked():
            self.seg_visualizer.add_vessel_volume(
                self.seg_result["mask"],
                self.seg_result["spacing"],
                self.seg_result["origin"],
            )
        self.iren.Render()

    def _render_right_masked_ct(self, result):
        mask = result["mask"].astype(np.uint8)
        spacing = result["spacing"]
        origin = result["origin"]
        shape = mask.shape

        vtk_img = vtk.vtkImageData()
        vtk_img.SetDimensions(shape[2], shape[1], shape[0])
        vtk_img.SetSpacing(spacing)
        vtk_img.SetOrigin(origin)
        flat = mask.ravel(order="C")
        vtk_arr = numpy_support.numpy_to_vtk(flat, deep=True, array_type=vtk.VTK_UNSIGNED_CHAR)
        vtk_img.GetPointData().SetScalars(vtk_arr)

        if self.right_volume:
            self.seg_renderer.RemoveVolume(self.right_volume)

        self.right_producer = vtk.vtkTrivialProducer()
        self.right_producer.SetOutput(vtk_img)

        self.right_mapper = vtk.vtkGPUVolumeRayCastMapper()
        self.right_mapper.SetInputConnection(self.right_producer.GetOutputPort())
        self.right_mapper.SetBlendModeToComposite()

        ofun = vtk.vtkPiecewiseFunction()
        ofun.AddPoint(0, 0.0)
        ofun.AddPoint(1, 0.6)
        cfun = vtk.vtkColorTransferFunction()
        cfun.AddRGBPoint(0, 0.0, 0.0, 0.0)
        cfun.AddRGBPoint(1, 1.0, 0.25, 0.15)

        right_prop = vtk.vtkVolumeProperty()
        right_prop.SetScalarOpacity(ofun)
        right_prop.SetColor(cfun)
        right_prop.SetInterpolationTypeToLinear()
        right_prop.ShadeOn()
        right_prop.SetAmbient(0.2)
        right_prop.SetDiffuse(0.8)
        right_prop.SetSpecular(0.1)
        right_prop.SetSpecularPower(5.0)

        self.right_volume = vtk.vtkVolume()
        self.right_volume.SetMapper(self.right_mapper)
        self.right_volume.SetProperty(right_prop)
        self.seg_renderer.AddVolume(self.right_volume)


def main() -> int:
    parser = argparse.ArgumentParser(description="PySide6 SSD+VR DICOM viewer (Figure 8 style fusion).")
    parser.add_argument("--input", default="", help="DICOM folder path or a single DICOM file")
    args = parser.parse_args()

    set_appearance_mode("dark")
    theme_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scientific.json")
    set_color_theme(theme_path)

    app = QtWidgets.QApplication(sys.argv)

    qss_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dark.qss")
    with open(qss_path, "r", encoding="utf-8") as f:
        app.setStyleSheet(f.read())

    win = ViewerWindow(initial_input=args.input.strip())
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
