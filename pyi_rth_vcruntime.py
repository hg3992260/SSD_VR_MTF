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

# --- 冻结版环境变量：必须在任何第三方库（torch / numpy / sklearn）导入之前生效 ---
#
# 不加这一行，Intel OpenMP 运行库的重复初始化会直接 abort 掉整个进程
# （在源码环境实测 exit code 3）：
#   OMP: Error #15: Initializing libiomp5md.dll, but found libiomp5md.dll
#                  already initialized.
# 源码里靠 sklearn/__init__.py、segmentation/sam_adapter.py 里的 setdefault 兜住，
# 但冻结版里谁先导入并不确定；放在 runtime hook 最稳——它在主脚本之前执行。
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")


def _preload() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
    except Exception:
        return

    meipass = getattr(sys, "_MEIPASS", "") or os.path.dirname(os.path.abspath(sys.executable))
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    candidates = [
        meipass,
        exe_dir,
        os.path.join(meipass, "sklearn", ".libs"),
        os.path.join(meipass, "scipy", ".libs"),
        os.path.join(meipass, "torch", "lib"),
    ]

    # 顺序关键：先加载被依赖项，再加载 vcomp140/msvcp140 本身。
    # 一旦 vcomp140.dll 被我们预加载，sklearn 的 WinDLL(vcomp140) 会复用已加载模块，
    # 从而彻底绕过 Windows DLL 搜索路径问题。
    for name in ("vcruntime140_1.dll", "vcruntime140.dll", "msvcp140.dll",
                 "vcomp140.dll", "concrt140.dll"):
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

    # --- 注册**所有** delvewheel 的 .libs 目录 -------------------------------
    #
    # delvewheel 会把依赖改名成 <name>-<32位十六进制哈希>.dll；PyInstaller 按
    # 文件名去重，于是某个包的 .pyd 需要的 DLL 可能被放进**另一个包**的 .libs。
    # 实例：cc3d\fastcc3d.cp310-win_amd64.pyd 依赖
    #   msvcp140-a4c2229bdc2a2a630acdc095b4d86008.dll
    # 而它只存在于 _internal\pandas.libs\，所以 import cc3d 直接抛
    #   ImportError: DLL load failed while importing fastcc3d: 找不到指定的模块。
    # 只有 pandas 恰好先被导入时才会碰巧成功 —— 典型的顺序依赖。
    # 预先注册全部 .libs 目录后，PE 导入表在任何导入顺序下都能解析。
    # （构建期还会用 tools/check_bundle_dlls.py --flatten 把它们摊到
    #    _internal\ 根目录，这里是第二道保险。）
    def _register_libs(root: str) -> None:
        if not os.path.isdir(root):
            return
        try:
            entries = os.listdir(root)
        except OSError:
            return
        for name in entries:
            p = os.path.join(root, name)
            if not os.path.isdir(p):
                continue
            if name.endswith(".libs"):            # _internal\pandas.libs
                try:
                    _handles.append(os.add_dll_directory(p))
                except Exception:
                    pass
                continue
            # 再下一层：_internal\sklearn\.libs
            try:
                for sub in os.listdir(p):
                    if sub.endswith(".libs"):
                        q = os.path.join(p, sub)
                        if os.path.isdir(q):
                            try:
                                _handles.append(os.add_dll_directory(q))
                            except Exception:
                                pass
            except OSError:
                pass

    for _root in (meipass, exe_dir):
        _register_libs(_root)


_preload()
