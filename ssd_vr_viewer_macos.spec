# -*- mode: python ; coding: utf-8 -*-
"""macOS .app 打包（PyInstaller spec）。

────────────────────────────────────────────────────────────────────────────
Qt 布局坑 —— 2026-09-17 DMG 启动 SIGABRT 复盘（务必先读）
────────────────────────────────────────────────────────────────────────────
现象: 打包后的 .app 启动即 abort()，Qt 原文 "Could not load the Qt platform plugin
      cocoa"；QT_DEBUG_PLUGINS=1 显示 libqcocoa.dylib 需要
      @rpath/libQt6Gui.6.dylib 而包里没有。

根因: CI 上同时存在**两套命名不同的 Qt**
        · conda-forge 的 vtk  → 裸 dylib 布局 (libQt6Core.6.dylib / libQt6Gui.6.dylib)
        · pip 的 PySide6       → macOS framework 布局 (QtGui.framework/Versions/A/QtGui)
      旧版 spec 有两段代码把「裸命名」的 libQt6*.dylib 全部从包里删掉（注释写的是
      "avoid conflict with PySide6's framework Qt"）。结果：裸命名的插件
      (libqcocoa.dylib、libvtkRenderingQt 依赖) 被留下，但它们需要的裸命名库被删光
      → 插件成孤儿 → QApplication 构造时 qFatal → abort() → SIGABRT。

修复原则（本文件遵守）:
  1. **绝不删除任何 Qt 库**。删库只在"全 pip 单套 Qt"的假设下成立，本项目不成立。
  2. 插件与裸 dylib 从 **pip 与 conda 两种布局**都能收到，统一落到
     PySide6/Qt/plugins 与 PySide6/Qt/lib，并写 Resources/qt.conf 告诉 Qt 去哪找。
  3. 版本必须同源同版：插件 6.11.2 配 6.11.0 的库会因缺符号失败
     (Symbol not found: QPlatformVulkanInstance::beginFrame)。所以 CI 侧
     (macos.yml) 把 Qt 统一到 conda-forge 的 pyside6，并用
     tools/verify_macos_bundle.sh 做硬门禁。
  4. 运行时兜底见 ssd_vr_viewer.py 的 _setup_macos_qt_paths()：多个候选目录都试一遍。
"""
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

# ── PyCt6: 强制收集数据文件（主题 JSON）+ 二进制
pct6_datas, pct6_bins, pct6_hidden = collect_all('PyCt6')
# ── VTK（Python 包；libvtk*.dylib 由 PyInstaller 的 vtkmodules hook + 依赖分析收）
vtk_datas, vtk_bins, vtk_hidden = collect_all('vtkmodules')
# ── SimpleITK
sitk_datas, sitk_bins, sitk_hidden = collect_all('SimpleITK')
# ── PySide6: 全量收集（Qt 框架/裸库 + 插件 + shiboken）
ps6_datas, ps6_bins, ps6_hidden = collect_all('PySide6')

# ────────────────────────────────────────────────────────────────────────────
# Qt 插件 / 裸 dylib 显式收集（pip framework 与 conda dylib 两种布局都覆盖）
# 全部只为"补漏"：目录不存在就跳过，任何异常都不该弄挂构建。
# ────────────────────────────────────────────────────────────────────────────
QT_PLUGIN_DST = 'PySide6/Qt/plugins'
QT_LIB_DST = 'PySide6/Qt/lib'
QT_LIB_GLOBS = ('libQt6*.dylib', 'libQt*.dylib', 'libicu*.dylib')
QT_PLUGIN_SUBDIRS = ('platforms', 'styles', 'imageformats', 'iconengines',
                     'platformthemes', 'platforminputcontexts', 'tls',
                     'generic', 'networkinformation', 'printsupport')


def _prefixes():
    """可能装着 Qt 的前缀：conda 环境、当前解释器前缀、解释器所在目录。"""
    out = []
    for p in (os.environ.get('CONDA_PREFIX'), os.environ.get('PREFIX'),
              sys.prefix, os.path.dirname(os.path.dirname(sys.executable)),
              os.path.dirname(sys.executable)):
        if p and p not in out:
            out.append(p)
    return out


def _pyside6_roots():
    out = []
    try:
        import PySide6  # noqa: PLC0415
        out.append(Path(PySide6.__path__[0]))
    except Exception:
        pass
    for p in _prefixes():
        for cand in (Path(p) / 'lib', Path(p)):
            try:
                for sp in cand.glob('python3.*/site-packages/PySide6'):
                    out.append(sp)
            except Exception:
                pass
    return [r for r in out if r.is_dir()]


def _plugin_dirs():
    out = []
    for root in _pyside6_roots():
        out += [root / 'Qt' / 'plugins', root / 'plugins']
    for p in _prefixes():
        base = Path(p)
        out += [base / 'lib' / 'qt6' / 'plugins', base / 'plugins',
                base / 'lib' / 'plugins', base / 'share' / 'qt6' / 'plugins']
    return [d for d in out if d.is_dir()]


def _lib_dirs():
    out = []
    for root in _pyside6_roots():
        out += [root / 'Qt' / 'lib', root / 'Qt' / 'libexec']
    for p in _prefixes():
        base = Path(p)
        out += [base / 'lib', base / 'lib' / 'qt6', base / 'lib' / 'qt6' / 'lib']
    return [d for d in out if d.is_dir()]


qt_bins = []
qt_datas = []
_plug_seen = set()
for _d in _plugin_dirs():
    for _f in sorted(_d.rglob('*')):
        if not _f.is_file() or _f.is_symlink():
            continue
        _rel = _f.relative_to(_d).as_posix()
        if _rel in _plug_seen:
            continue
        _plug_seen.add(_rel)
        _sub = os.path.dirname(_rel)
        _dest = f'{QT_PLUGIN_DST}/{_sub}' if _sub else QT_PLUGIN_DST
        if _f.suffix in ('.dylib', '.so'):
            qt_bins.append((str(_f), _dest))
        else:
            qt_datas.append((str(_f), _dest))

_lib_seen = set()
for _d in _lib_dirs():
    for _pat in QT_LIB_GLOBS:
        for _f in sorted(_d.glob(_pat)):
            if not _f.is_file() or _f.is_symlink():
                continue
            if _f.name in _lib_seen:
                continue
            _lib_seen.add(_f.name)
            qt_bins.append((str(_f), QT_LIB_DST))

print(f'[spec] Qt plugin dirs: {[str(d) for d in _plugin_dirs()]}')
print(f'[spec] Qt lib dirs   : {[str(d) for d in _lib_dirs()]}')
print(f'[spec] +{len(qt_bins)} Qt binaries, +{len(qt_datas)} Qt data files')

# ── Resources/qt.conf：macOS 上 Qt 会读 Contents/Resources/qt.conf
_qtconf_dir = Path('build_qtconf')
_qtconf_dir.mkdir(exist_ok=True)
_qtconf = _qtconf_dir / 'qt.conf'
_qtconf.write_text(
    '[Paths]\n'
    'Prefix = .\n'
    f'Plugins = {QT_PLUGIN_DST}\n'
    f'Libraries = {QT_LIB_DST}\n',
    encoding='utf-8',
)

a = Analysis(
    ['ssd_vr_viewer.py'],
    pathex=[],
    binaries=pct6_bins + vtk_bins + sitk_bins + ps6_bins + qt_bins,
    datas=pct6_datas + vtk_datas + sitk_datas + ps6_datas + qt_datas + [
        ('scientific.json', '.'),
        ('dark.qss', '.'),
        ('presets.xml', '.'),
        ('logo.jpg', '.'),
        ('segmentation', 'segmentation'),
        ('mcp_ssd_vr', 'mcp_ssd_vr'),
        (str(_qtconf), '.'),
    ],
    hiddenimports=[
        'PyCt6',
        'PyCt6.widgets.c_button', 'PyCt6.widgets.c_label', 'PyCt6.widgets.c_line_edit',
        'PyCt6.widgets.c_combo_box', 'PyCt6.widgets.c_slider', 'PyCt6.widgets.c_frame',
        'PyCt6.widgets.c_text_edit',
        'PyCt6.windows.c_main_window',
        'PyCt6.appearance.theme_manager', 'PyCt6.appearance.mode_manager',
        'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets',
        'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets', 'PySide6.QtSvg',
        'PySide6.QtNetwork', 'PySide6.QtDBus', 'PySide6.QtPrintSupport',
        'vtkmodules.qt.QVTKRenderWindowInteractor', 'vtkmodules.util.numpy_support',
        'scipy.ndimage', 'skimage.restoration', 'skimage.filters',
        'nibabel', 'nibabel.nifti1',
        'mcp_ssd_vr.gui_bridge', 'mcp_ssd_vr.bridge_client',
        'mcp_ssd_vr.bridge_registry', 'mcp_ssd_vr.state', 'mcp_ssd_vr.config',
        'mcp_ssd_vr.recorder',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 注意：这里**不能**排除 PySide6.QtNetwork / QtDBus —— cocoa 插件会用到它们。
    excludes=['tkinter', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
              'PySide6.QtWebEngineQuick', 'PySide6.QtQuick', 'PySide6.QtQuickWidgets'],
    noarchive=False,
)

# 兜底：万一某条目重复（hook 已收过），保留第一个，避免 PyInstaller 报 duplicate。
try:
    from PyInstaller.building.datastruct import TOC

    def _dedupe(toc):
        seen, out = set(), []
        for entry in toc:
            if entry[0] in seen:
                continue
            seen.add(entry[0])
            out.append(entry)
        return TOC(out)

    a.binaries = _dedupe(a.binaries)
    a.datas = _dedupe(a.datas)
except Exception as _e:  # pragma: no cover - 只影响噪音，不影响可用性
    print(f'[spec] dedupe skipped: {_e}')

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
    upx=False,            # macOS 上 UPX 无意义且可能破坏签名
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
    upx=False,
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
        # 注意：LSEnvironment 里不放 @executable_path（LaunchServices 不展开它）。
        # 插件路径由 Resources/qt.conf + ssd_vr_viewer._setup_macos_qt_paths() 兜底。
    },
)
