# -*- mode: python ; coding: utf-8 -*-
"""macOS .app 打包（PyInstaller spec）。

════════════════════════════════════════════════════════════════════════════
两次崩溃的复盘（务必先读；改这个文件前请确认你理解这两条）
════════════════════════════════════════════════════════════════════════════
【第一次】SIGABRT：QApplication 构造时 qFatal
  现象: "Could not load the Qt platform plugin cocoa"，
        QT_DEBUG_PLUGINS=1 显示 libqcocoa.dylib 需要 @rpath/libQt6Gui.6.dylib 而包里没有。
  原因: CI 上同时装了两套 Qt —— conda-forge 的 vtk 链接**裸 dylib** Qt，
        pip 的 PySide6 是 **framework** Qt；旧 spec 有两段代码把裸命名的
        libQt6*.dylib 全部删掉（"avoid conflict with PySide6's framework Qt"），
        于是裸命名的插件成了孤儿。
  修法: 不再删任何 Qt（本文件已无任何过滤）。

【第二次】EXC_BAD_ACCESS：事件循环里随机崩（processExposeEvent → NSOpenGLView）
  现象: 启动日志里 "Class QMetalLayer is implemented in both
        .../libQt6Gui.6.dylib and .../PySide6/Qt/lib/QtGui.framework/.../QtGui"。
  原因: 只"不删"还不够 —— 两个发行版的 Qt 会**同时进包**，同一个 Qt 出现三份：
        Frameworks/libQt6*.dylib（conda）+ Frameworks/PySide6/Qt/lib/libQt6*.6.11.2.dylib
        （pip wheel）+ Frameworks/PySide6/Qt/lib/Qt*.framework（pip wheel）。
        ObjC 类重复注册 → 随机崩溃。
  修法: ① CI 侧把 Qt 统一到 conda-forge 的 pyside6（见 .github/workflows/macos.yml，
        关键是 `pip install --no-deps PyCt6`，否则 pip 又把 wheel 版拉回来）；
        ② 本文件和 CI 都有"只允许一套 Qt"的守卫：宁可构建失败，也不产出会崩的包。

用户级结论：**Qt 只能有一个来源**。本 spec 只做三件事：
  1. 四个 collect_all（PyCt6 / vtkmodules / SimpleITK / PySide6）—— 与已知能跑的
     DICOM_Analysis_Tool.app 的 spec 同构（它没有任何 Qt 过滤）；
  2. Qt 库/插件**不做显式重复收集**（交给 PyInstaller 的 PySide6 hook + 依赖分析，
     显式再收一份只会制造 "implemented in both"）；只有在 hook 完全没收到
     cocoa 插件时才补一次兜底；
  3. 构建期守卫 _qt_audit()：出现两套 Qt 发行版、或同一个 Qt 组件落在两个 dest，
     直接 SystemExit 并打印修复指引。
"""
import os
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

# ── 四个包全量收集 ───────────────────────────────────────────────────────────
pct6_datas, pct6_bins, pct6_hidden = collect_all('PyCt6')
vtk_datas, vtk_bins, vtk_hidden = collect_all('vtkmodules')
sitk_datas, sitk_bins, sitk_hidden = collect_all('SimpleITK')
ps6_datas, ps6_bins, ps6_hidden = collect_all('PySide6')

# ── 兜底用的 Qt 插件候选目录（只在 hook 没跑到时才用；正常构建不会用到） ─────
QT_PLUGIN_DST = 'PySide6/Qt/plugins'


def _prefixes():
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
                out += list(cand.glob('python3.*/site-packages/PySide6'))
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


a = Analysis(
    ['ssd_vr_viewer.py'],
    pathex=[],
    binaries=pct6_bins + vtk_bins + sitk_bins + ps6_bins,
    datas=pct6_datas + vtk_datas + sitk_datas + ps6_datas + [
        ('scientific.json', '.'),
        ('dark.qss', '.'),
        ('presets.xml', '.'),
        ('logo.jpg', '.'),
        ('segmentation', 'segmentation'),
        ('mcp_ssd_vr', 'mcp_ssd_vr'),
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
    # 注意：**不能**排除 PySide6.QtNetwork / QtDBus —— cocoa 插件会用到。
    excludes=['tkinter', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
              'PySide6.QtWebEngineQuick', 'PySide6.QtQuick', 'PySide6.QtQuickWidgets'],
    noarchive=False,
)


# ════════════════════════════════════════════════════════════════════════════
# 构建期守卫 1/2：cocoa 插件兜底（只在 hook 一个都没收到时才补，绝不重复）
# ════════════════════════════════════════════════════════════════════════════
def _has_cocoa(toc):
    return any('libqcocoa' in str(e[0]) for e in toc)


if not (_has_cocoa(a.binaries) or _has_cocoa(a.datas)):
    print('[spec] WARNING: PySide6 hook 没收集到平台的 libqcocoa，改用兜底收集')
    _seen = set()
    for _d in _plugin_dirs():
        for _f in sorted(_d.rglob('*')):
            if not _f.is_file() or _f.is_symlink():
                continue
            _rel = _f.relative_to(_d).as_posix()
            if _rel in _seen:
                continue
            _seen.add(_rel)
            _sub = os.path.dirname(_rel)
            _dest = f'{QT_PLUGIN_DST}/{_sub}' if _sub else QT_PLUGIN_DST
            if _f.suffix in ('.dylib', '.so'):
                a.binaries.append((_dest, str(_f), 'BINARY'))
            else:
                a.datas.append((_dest, str(_f), 'DATA'))
    print(f'[spec] 兜底补入 {len(_seen)} 个插件文件')
else:
    print('[spec] cocoa 插件已由 hook 收集，跳过兜底')


# ════════════════════════════════════════════════════════════════════════════
# 构建期守卫 2/2：只允许**一套** Qt
#
# 判据（对应两次崩溃）：
#   · 发行版数 > 1        -> 两套 Qt（pip wheel 在 /PySide6/Qt/ 下，conda 在
#                            Frameworks/ 根或 lib/ 下）→ SIGABRT / 随机崩
#   · 同名组件落在 >1 个 dest -> 同一个 Qt 装了两遍 → ObjC 类重复注册
#     例如 libQt6Core.6.dylib（conda）与 QtCore.framework/...（wheel）并存。
# ════════════════════════════════════════════════════════════════════════════
_QT_FW_RE = re.compile(r'(?:^|/)Qt[A-Za-z0-9_]*\.framework/')


def _qt_audit(tocs):
    families = set()
    dests_by_key = {}
    for toc in tocs:
        for entry in toc:
            dest = '/' + str(entry[0]).replace('\\', '/').lstrip('/')
            base = dest.rsplit('/', 1)[-1]
            is_lib = base.startswith('libQt6') and base.endswith('.dylib')
            is_fw = bool(_QT_FW_RE.search(dest))
            if not (is_lib or is_fw):
                continue
            families.add('wheel' if '/PySide6/Qt/' in dest else 'conda')
            key = base if is_lib else dest.split('.framework/')[0].rsplit('/', 1)[-1] + '.framework'
            dests_by_key.setdefault(key, []).append(dest)
    dupes = {k: sorted(set(v)) for k, v in dests_by_key.items() if len(set(v)) > 1}
    return sorted(families), dupes


_families, _dupes = _qt_audit([a.binaries, a.datas])
print(f'[spec] Qt 发行版: {_families}')
if _dupes:
    print(f'[spec] Qt 重复组件: {list(_dupes.items())[:8]}')

_FIX_HINT = (
    '\n'
    '──────────────────────────────────────────────────────────────────────\n'
    'Qt 只能有一个来源，但当前构建检测到多套/重复：\n'
    f'  发行版      : {_families}\n'
    f'  重复组件    : {list(_dupes)[:8]}\n'
    '\n'
    'CI（.github/workflows/macos.yml）必须是：\n'
    '  conda install -y -c conda-forge vtk pyside6     # Qt 统一到 conda-forge\n'
    '  pip install --no-deps PyCt6                     # 不能让它把 wheel 版 PySide6 拉回来\n'
    '  # 绝不要再 pip install PySide6\n'
    '本地构建同理：先把 pip 的 PySide6 / PyQt 卸干净再打包。\n'
    '背景见 ssd_vr_viewer_macos.spec 顶部与 tools/verify_macos_bundle.sh。\n'
    '──────────────────────────────────────────────────────────────────────\n'
)
if len(_families) > 1:
    raise SystemExit('[spec] FAIL: 检测到两套 Qt 发行版 ' + str(_families) + _FIX_HINT)
if _dupes:
    raise SystemExit('[spec] FAIL: 同一个 Qt 组件被装了两遍 ' + str(list(_dupes)[:8]) + _FIX_HINT)

# 去重兜底（万一 hook 与 collect_all 撞了同一 dest，保留第一个）
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
except Exception as _e:  # pragma: no cover
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
        # 不放 LSEnvironment：LaunchServices 不会展开 @executable_path。
        # 插件路径由 PySide6 自带的 qt.conf + ssd_vr_viewer._setup_macos_qt_paths() 兜底。
    },
)
