#!/usr/bin/env python3
"""跨平台 Mach-O 依赖自洽性检查（不需要 macOS 的 otool / dyld）。

用途：在 Windows/Linux 上离线验证一个 .app bundle 是否自洽 —— 每个 Mach-O 二进制的
LC_LOAD_DYLIB 依赖是否都能在 bundle 内解析。macOS 冻结包"启动即 abort()"最常见的原因
就是平台插件（libqcocoa.dylib）的某个 Qt 依赖没打进包（见 MCP_EXE_BRIDGE.md 与
tools/verify_macos_bundle.sh 的 2026-09-17 复盘）。

用法:
    python tools/macho_bundle_check.py path/to/SSD_VR_Fusion_Viewer.app
    python tools/macho_bundle_check.py path/to/Some.dylib --json

退出码: 0 全部可解析 / 1 有未解析依赖或发现两套 Qt / 2 用法错误
"""
from __future__ import annotations

import json
import os
import struct
import sys
from typing import Dict, List, Optional, Tuple

MH_MAGIC_64 = 0xFEEDFACF
MH_CIGAM_64 = 0xCFFAEDFE
MH_MAGIC_32 = 0xFEEDFACE
MH_CIGAM_32 = 0xCEFAEDFE
FAT_MAGIC = 0xCAFEBABE
FAT_CIGAM = 0xBEBAFECA
FAT_MAGIC_64 = 0xCAFEBABF

LC_REQ_DYLD = 0x80000000
LC_ID_DYLIB = 0x0D
LC_LOAD_DYLIB = 0x0C
LC_LOAD_WEAK_DYLIB = 0x18 | LC_REQ_DYLD
LC_REEXPORT_DYLIB = 0x1F | LC_REQ_DYLD
LC_LOAD_UPWARD_DYLIB = 0x23 | LC_REQ_DYLD
LC_LAZY_LOAD_DYLIB = 0x20
LC_RPATH = 0x1C | LC_REQ_DYLD

DEP_CMDS = {LC_LOAD_DYLIB, LC_LOAD_WEAK_DYLIB, LC_REEXPORT_DYLIB,
            LC_LOAD_UPWARD_DYLIB, LC_LAZY_LOAD_DYLIB}

SYSTEM_PREFIXES = ("/usr/lib/", "/System/", "/Library/Apple/")


def _read_cstr(data: bytes, offset: int) -> str:
    end = data.find(b"\x00", offset)
    if end < 0:
        end = len(data)
    return data[offset:end].decode("utf-8", "replace")


def _slices(data: bytes) -> List[Tuple[int, int]]:
    """返回 [(offset, size)]；fat 二进制取第一个架构切片。"""
    if len(data) < 8:
        return []
    magic = struct.unpack_from(">I", data, 0)[0]
    if magic in (FAT_MAGIC, FAT_MAGIC_64):
        nfat = struct.unpack_from(">I", data, 4)[0]
        if nfat <= 0 or len(data) < 8 + 20:
            return []
        offset, size = struct.unpack_from(">II", data, 8 + 8)
        return [(offset, size)]
    return [(0, len(data))]


def parse_macho(data: bytes) -> Optional[dict]:
    """解析第一个架构切片，返回 {deps, rpaths, install_name}。非 Mach-O 返回 None。"""
    for off, _size in _slices(data):
        if len(data) < off + 32:
            continue
        magic_le = struct.unpack_from("<I", data, off)[0]
        magic_be = struct.unpack_from(">I", data, off)[0]
        if magic_le == MH_MAGIC_64:
            endian, is64 = "<", True
        elif magic_be == MH_MAGIC_64:
            endian, is64 = ">", True
        elif magic_le == MH_MAGIC_32:
            endian, is64 = "<", False
        elif magic_be == MH_MAGIC_32:
            endian, is64 = ">", False
        else:
            continue

        ncmds, sizeofcmds = struct.unpack_from(endian + "II", data, off + 16)
        header_size = 32 if is64 else 28
        pos = off + header_size
        deps: List[str] = []
        rpaths: List[str] = []
        install_name = ""
        for _ in range(ncmds):
            if pos + 8 > len(data):
                break
            cmd, cmdsize = struct.unpack_from(endian + "II", data, pos)
            if cmdsize < 8:
                break
            if cmd in DEP_CMDS:
                name_off = struct.unpack_from(endian + "I", data, pos + 8)[0]
                deps.append(_read_cstr(data, pos + name_off))
            elif cmd == LC_ID_DYLIB:
                name_off = struct.unpack_from(endian + "I", data, pos + 8)[0]
                install_name = _read_cstr(data, pos + name_off)
            elif cmd == LC_RPATH:
                name_off = struct.unpack_from(endian + "I", data, pos + 8)[0]
                rpaths.append(_read_cstr(data, pos + name_off))
            pos += cmdsize
        return {"deps": deps, "rpaths": rpaths, "install_name": install_name,
                "is64": is64, "endian": endian}
    return None


def is_macho(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(4)
    except OSError:
        return False
    if len(head) < 4:
        return False
    magic = struct.unpack("<I", head)[0]
    return magic in (MH_MAGIC_64, MH_MAGIC_32, FAT_MAGIC, FAT_CIGAM, FAT_MAGIC_64)


def scan_bundle(root: str) -> Dict[str, dict]:
    """遍历 bundle 里所有 Mach-O 文件，返回 {相对路径: 解析结果}。"""
    out: Dict[str, dict] = {}
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                continue
            if not (name.endswith(".dylib") or name.endswith(".so")
                    or "." not in name or name.endswith(".abi3.so")):
                # 无扩展名的可执行文件也要看；有其它扩展名的跳过
                if "." in name:
                    continue
            if not is_macho(full):
                continue
            info = parse_macho(open(full, "rb").read())
            if info is None:
                continue
            out[os.path.relpath(full, root).replace("\\", "/")] = info
    return out


def _basename_index(files: Dict[str, dict]) -> Dict[str, str]:
    idx: Dict[str, str] = {}
    for rel in files:
        idx.setdefault(os.path.basename(rel), rel)
    return idx


def resolve(dep: str, owner_rel: str, rpaths: List[str],
            by_base: Dict[str, str], files: Dict[str, dict]) -> Optional[str]:
    """把一条依赖解析成 bundle 内相对路径；系统库直接视为 OK（返回其自身）。"""
    if dep.startswith(SYSTEM_PREFIXES) or dep.startswith("/usr/lib"):
        return dep
    if dep.startswith("@rpath/"):
        tail = dep[len("@rpath/"):]
        cands = [rp.replace("@loader_path", os.path.dirname("/" + owner_rel))
                   .replace("@executable_path", "Contents/MacOS") + "/" + tail
                 for rp in rpaths]
        cands += [f"Contents/Frameworks/{tail}",
                  f"Contents/Resources/PySide6/Qt/lib/{tail}",
                  f"Contents/Resources/lib/{tail}",
                  tail]
    elif dep.startswith("@loader_path/"):
        cands = [os.path.join(os.path.dirname(owner_rel), dep[len("@loader_path/"):])]
    elif dep.startswith("@executable_path/"):
        cands = [os.path.join("Contents/MacOS", dep[len("@executable_path/"):])]
    else:
        # 绝对路径：先看是不是 bundle 内自己的文件（冻结包常见绝对路径泄露），
        # 再退化到按文件名在包里找
        rel = dep.lstrip("/")
        cands = [rel, dep]
        base = os.path.basename(dep)
        if base in by_base:
            return by_base[base]

    for c in cands:
        norm = os.path.normpath(c).replace("\\", "/")
        if norm in files:
            return norm
        if os.path.isabs(dep) and os.path.isfile(dep):
            return dep
    base = os.path.basename(dep)
    if base in by_base:
        return by_base[base]
    if os.path.isabs(dep) and os.path.isfile(dep):
        return dep
    return None


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    root = sys.argv[1]
    as_json = "--json" in sys.argv
    if not os.path.isdir(root):
        print(f"不是目录: {root}")
        return 2

    files = scan_bundle(root)
    by_base = _basename_index(files)
    problems: List[str] = []
    report = {"root": root, "macho_files": len(files), "unresolved": {}, "consumers": {}}

    for rel, info in sorted(files.items()):
        missing = []
        for dep in info["deps"]:
            if resolve(dep, rel, info["rpaths"], by_base, files) is None:
                missing.append(dep)
        if missing:
            report["unresolved"][rel] = missing
            problems.append(f"{rel} 缺少依赖: {', '.join(missing)}")

    # 两套 Qt 检测
    naked = [r for r in files if os.path.basename(r).startswith("libQt6") and r.endswith(".dylib")]
    framed = [r for r in files if ".framework/" in r and "/Versions/" in r]
    report["naked_qt"] = sorted(os.path.basename(r) for r in naked)
    report["framework_qt"] = sorted({r.split(".framework/")[0].split("/")[-1] for r in framed})

    # 关键消费方
    for key in ("platforms/libqcocoa.dylib",):
        hits = [r for r in files if r.endswith(key)]
        for h in hits:
            report["consumers"][h] = [d for d in files[h]["deps"] if "Qt" in d]

    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"bundle      : {root}")
        print(f"Mach-O 文件 : {len(files)}")
        print(f"裸 Qt 库    : {len(naked)} 个  {report['naked_qt'][:8]}")
        print(f"framework Qt: {len(framed)} 个  {report['framework_qt'][:8]}")
        for h, deps in report["consumers"].items():
            print(f"\n{h} 的 Qt 依赖:")
            for d in deps:
                mark = "ok  " if resolve(d, h, files[h]["rpaths"], by_base, files) else "MISS"
                print(f"  [{mark}] {d}")
        print()
        if problems:
            print(f"未解析依赖 {len(problems)} 处:")
            for p in problems[:40]:
                print("  - " + p)
        else:
            print("所有 Mach-O 依赖都能在 bundle 内解析。")

    bad = bool(problems)
    if naked and framed:
        bad = True
        print("\n[FAIL] 同时存在裸 dylib Qt 与 framework Qt（两套 Qt）—— "
              "见 .github/workflows/macos.yml：Qt 必须统一到 conda-forge 的 pyside6。")
    print("\nVERDICT: " + ("FAIL" if bad else "PASS"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
