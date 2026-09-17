#!/usr/bin/env bash
# macOS .app 自洽性硬门禁 —— 防止再次发出"启动即 SIGABRT"的 DMG。
#
# 背景: 2026-09-17 的 DMG 启动崩溃（QApplication → qFatal → abort()），根因是包里
# 的裸命名平台插件 libqcocoa.dylib 需要的 libQt6Gui.6.dylib 被 spec 过滤掉了
# （原因：CI 同时装了 conda 的裸 dylib Qt 与 pip 的 framework Qt，两套 Qt）。
# 这个脚本静态校验依赖闭合 + 真启动冒烟，任一失败即 exit 1。
#
# 用法:
#   bash tools/verify_macos_bundle.sh dist/SSD_VR_Fusion_Viewer.app
# 可选环境变量:
#   SKIP_SMOKE=1     跳过启动冒烟（只做静态校验）
#   SMOKE_TIMEOUT=25 冒烟观察秒数
set -u

APP="${1:-dist/SSD_VR_Fusion_Viewer.app}"
EXE_NAME="SSD_VR_Fusion_Viewer"
SMOKE_TIMEOUT="${SMOKE_TIMEOUT:-25}"
FAILURES=0

ok()   { printf '  [ok]   %s\n' "$1"; }
bad()  { printf '  [FAIL] %s\n' "$1"; FAILURES=$((FAILURES + 1)); }
info() { printf '  [info] %s\n' "$1"; }
head() { printf '\n== %s ==\n' "$1"; }

head "1. bundle 结构"
if [ ! -d "$APP" ]; then
  printf '找不到 app bundle: %s\n' "$APP"
  exit 2
fi
APP_EXE="$APP/Contents/MacOS/$EXE_NAME"
APP_RES="$APP/Contents/Resources"
[ -x "$APP_EXE" ] && ok "可执行文件: $APP_EXE" || bad "找不到可执行文件 $APP_EXE"
[ -d "$APP_RES" ] && ok "Resources 目录存在" || bad "缺少 Contents/Resources"

head "2. Qt 平台插件（cocoa）"
COCOA=$(find "$APP" -name 'libqcocoa.dylib' 2>/dev/null | head -n 1)
if [ -n "$COCOA" ]; then
  ok "libqcocoa.dylib: ${COCOA#$APP/}"
else
  bad "包里没有 libqcocoa.dylib —— Qt 无法初始化 cocoa 平台，必崩"
fi
PLATFORM_COUNT=$(find "$APP" -path '*plugins/platforms/*.dylib' 2>/dev/null | wc -l | tr -d ' ')
info "platforms/ 下插件数: $PLATFORM_COUNT"

head "3. Qt 库依赖闭合（对照消费方的 otool -L）"
DEPS_TMP=$(mktemp)
CONSUMERS=$(find "$APP" \( -name 'libqcocoa.dylib' -o -name 'libvtkRenderingQt*.dylib' \) 2>/dev/null)
if [ -z "$CONSUMERS" ]; then
  bad "找不到消费方（libqcocoa / libvtkRenderingQt），无法校验依赖闭合"
else
  for consumer in $CONSUMERS; do
    base=$(basename "$consumer")
    # 只关心 Qt 相关依赖（裸 dylib 或 framework 内部二进制）
    otool -L "$consumer" 2>/dev/null | tail -n +2 | awk '{print $1}' \
      | grep -E 'libQt6[A-Za-z0-9]*\.dylib$|Qt6[A-Za-z0-9]*\.framework' | sort -u > "$DEPS_TMP" || true
    if [ ! -s "$DEPS_TMP" ]; then
      info "$base: 没有 Qt 依赖（可能是静态链接？）"
      continue
    fi
    while IFS= read -r dep; do
      [ -n "$dep" ] || continue
      name=$(basename "$dep")
      if find "$APP" -name "$name" 2>/dev/null | grep -q .; then
        ok "$base -> $name"
      else
        bad "$base 需要 $name，但包里找不到（这正是 SIGABRT 的直接原因）"
      fi
    done < "$DEPS_TMP"
  done
fi
rm -f "$DEPS_TMP"

head "4. 不能同时存在两套 Qt（裸 dylib 与 framework）"
NAKED=$(find "$APP" -name 'libQt6Gui*.dylib' 2>/dev/null | wc -l | tr -d ' ')
FRAMED=$(find "$APP" -name 'QtGui' -path '*QtGui.framework*' 2>/dev/null | wc -l | tr -d ' ')
info "裸 dylib: $NAKED 个, framework: $FRAMED 个"
if [ "$NAKED" -gt 0 ] && [ "$FRAMED" -gt 0 ]; then
  bad "两套 Qt 同时入包 —— 版本/ABI 不同会互相打架，且插件只认其中一套。"
  bad "  修法见 .github/workflows/macos.yml：conda 装 vtk + pyside6（同源同版），"
  bad "  PyCt6 用 pip install --no-deps 装，绝不要再 pip install PySide6。"
else
  ok "Qt 只有一套"
fi

head "5. qt.conf"
if [ -f "$APP_RES/qt.conf" ]; then
  ok "Contents/Resources/qt.conf 存在"
  sed 's/^/         /' "$APP_RES/qt.conf"
else
  bad "缺少 Contents/Resources/qt.conf（Qt 找不到 Plugins 目录时会退回默认路径）"
fi

head "6. 启动冒烟（QT_DEBUG_PLUGINS=1，存活 ${SMOKE_TIMEOUT}s 即通过）"
if [ "${SKIP_SMOKE:-0}" = "1" ]; then
  info "SKIP_SMOKE=1，跳过"
elif [ ! -x "$APP_EXE" ]; then
  bad "没有可执行文件，跳过冒烟"
else
  SMOKE_LOG=$(mktemp)
  QT_DEBUG_PLUGINS=1 "$APP_EXE" --no-mcp > "$SMOKE_LOG" 2>&1 &
  SMOKE_PID=$!
  elapsed=0
  while [ "$elapsed" -lt "$SMOKE_TIMEOUT" ]; do
    sleep 1
    elapsed=$((elapsed + 1))
    kill -0 "$SMOKE_PID" 2>/dev/null || break
  done
  if kill -0 "$SMOKE_PID" 2>/dev/null; then
    ok "进程存活 ${SMOKE_TIMEOUT}s（GUI 已进入事件循环）"
    kill "$SMOKE_PID" 2>/dev/null || true
    wait "$SMOKE_PID" 2>/dev/null || true
  else
    bad "进程在 ${elapsed}s 内退出"
  fi
  # 明确匹配 Qt / abort 的致命字样
  for pat in 'Could not load the Qt platform plugin' \
             'no Qt platform plugin could be initialized' \
             'abort() called' 'SIGABRT'; do
    if grep -q "$pat" "$SMOKE_LOG" 2>/dev/null; then
      bad "启动日志命中致命字样: $pat"
    fi
  done
  printf '  ---- 启动日志（尾部 40 行）----\n'
  tail -n 40 "$SMOKE_LOG" | sed 's/^/  | /'
  rm -f "$SMOKE_LOG"
fi

printf '\n'
if [ "$FAILURES" -gt 0 ]; then
  printf 'VERDICT: FAIL  (%d 项不合格) —— 这个 .app/DMG 不要发布\n' "$FAILURES"
  exit 1
fi
printf 'VERDICT: PASS  —— bundle 自洽，可以打包 DMG\n'
exit 0
