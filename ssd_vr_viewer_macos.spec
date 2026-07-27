# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs

# – PyCt6: force collect data files (theme JSONs) + binaries
pct6_datas, pct6_bins, pct6_hidden = collect_all('PyCt6')
# – VTK
vtk_datas, vtk_bins, vtk_hidden = collect_all('vtkmodules')
# – SimpleITK
sitk_datas, sitk_bins, sitk_hidden = collect_all('SimpleITK')

extra_datas = []
extra_bins = list(pct6_bins) + list(vtk_bins) + list(sitk_bins)

# Filter standalone Qt dylibs to avoid conflict with PySide6's framework Qt
import fnmatch
_qt_standalone = {'libQt6Core*.dylib','libQt6Gui*.dylib','libQt6Widgets*.dylib',
                  'libQt6DBus*.dylib','libQt6Network*.dylib'}
extra_bins = [(src,dst) for src,dst in extra_bins
              if not any(fnmatch.fnmatch(dst.split('/')[-1], p) for p in _qt_standalone)]


a = Analysis(
    ['ssd_vr_viewer.py'],
    pathex=[],
    binaries=extra_bins,
    datas=pct6_datas + vtk_datas + sitk_datas + extra_datas + [
        ('scientific.json', '.'),
        ('dark.qss', '.'),
        ('presets.xml', '.'),
        ('logo.jpg', '.'),
        ('segmentation', 'segmentation'),
    ],
    hiddenimports=[
        'PyCt6',
        'PyCt6.widgets.c_button','PyCt6.widgets.c_label','PyCt6.widgets.c_line_edit',
        'PyCt6.widgets.c_combo_box','PyCt6.widgets.c_slider','PyCt6.widgets.c_frame',
        'PyCt6.widgets.c_text_edit',
        'PyCt6.windows.c_main_window',
        'PyCt6.appearance.theme_manager','PyCt6.appearance.mode_manager',
        'PySide6.QtCore','PySide6.QtGui','PySide6.QtWidgets',
        'PySide6.QtOpenGL','PySide6.QtOpenGLWidgets','PySide6.QtSvg',
        'vtkmodules.qt.QVTKRenderWindowInteractor','vtkmodules.util.numpy_support',
        'scipy.ndimage','skimage.restoration','skimage.filters',
        'nibabel','nibabel.nifti1',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter','PySide6.QtWebEngineCore','PySide6.QtWebEngineWidgets',
              'PySide6.QtWebEngineQuick','PySide6.QtQuick','PySide6.QtQuickWidgets',
              'PySide6.QtNetwork','PySide6.QtDBus'],
    noarchive=False,
)

# Exclude standalone libQt6*.dylib to avoid conflict with PySide6 framework Qt
from PyInstaller.building.datastruct import TOC
a.binaries = TOC([t for t in a.binaries
                  if not t[0].startswith('libQt6')])

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SSD_VR_Fusion_Viewer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='logo.jpg',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SSD_VR_Fusion_Viewer',
)

app = BUNDLE(
    coll,
    name='SSD_VR_Fusion_Viewer.app',
    icon='logo.jpg',
    bundle_identifier='com.ssdvr.fusion-viewer',
    info_plist={
        'NSHighResolutionCapable': True,
        'LSEnvironment': {'QT_PLUGIN_PATH': '@executable_path/../Resources/PySide6/Qt/plugins'},
    },
)
