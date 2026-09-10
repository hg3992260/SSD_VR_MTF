# PyInstaller runtime hook: 在导入 sklearn/scipy 等使用 MSVC OpenMP 运行库的
# 包之前，先把 vcruntime/msvcp/concrt 预加载进进程。
#
# 背景: sklearn 的 _distributor_init.py 会 WinDLL(绝对路径 vcomp140.dll)，
#       但 vcomp140.dll 依赖 vcruntime140.dll；Windows 默认 DLL 搜索路径不含
#       _internal/sklearn/.libs，导致 vcomp140 加载失败并被 PyInstaller 包装成
#       "Failed to load dynlib/dll ... vcomp140.dll"。
#       预先 LoadLibrary 这些依赖后，vcomp140 的依赖解析会复用已加载模块，
#       从而彻底绕过搜索路径问题。
import os
import sys


def _preload() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
    except Exception:
        return

    meipass = getattr(sys, "_MEIPASS", "") or os.path.dirname(os.path.abspath(sys.executable))
    candidates = [
        meipass,
        os.path.join(meipass, "sklearn", ".libs"),
        os.path.join(meipass, "scipy", ".libs"),
    ]

    # 顺序：先 vcruntime140_1（可能被 vcruntime140 依赖），再 vcruntime140，再 msvcp/concrt
    for name in ("vcruntime140_1.dll", "vcruntime140.dll", "msvcp140.dll", "concrt140.dll"):
        for d in candidates:
            p = os.path.join(d, name)
            if not os.path.isfile(p):
                continue
            try:
                ctypes.WinDLL(os.path.abspath(p))
                break
            except Exception:
                continue

    # 额外把候选目录加入 DLL 搜索路径（惠及其它 delvewheel 包）
    # 注意：add_dll_directory 返回的句柄必须持有，否则被 GC 后目录会被移除。
    _handles = []
    for d in candidates:
        if os.path.isdir(d):
            try:
                _handles.append(os.add_dll_directory(d))
            except Exception:
                pass


_preload()
