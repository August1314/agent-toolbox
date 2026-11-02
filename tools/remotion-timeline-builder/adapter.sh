#!/usr/bin/env bash
# adapter.sh —— remotion-timeline-builder 的薄适配层
#
# 契约（= index.yaml 里的 entry.usage，lookup 会原样转告）：
#   toolbox run remotion-timeline-builder --in <Remotion 项目目录>
#   产物路径由项目约定固定：<项目>/public/timeline.json（不接受 --out 改道）
#
# vendor/build-timeline.mjs 原样：它是从 expression-video 项目里验证跑通的脚本，
# 逻辑一个字没改。所有路径映射在本文件完成。
# 配音脚本唯一归 voice-over-neural-tts 所有，这里只引用、不再存第二份副本
# （两份 vendor 各自漂移 = 下一次改动的错会归给"不知道哪份是新的"）。

set -euo pipefail

PROJECT=""
SELFTEST=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --in) PROJECT="$2"; shift 2 ;;
    --out) echo "本工具输出路径由项目约定固定为 <项目>/public/timeline.json，--out 无效。" >&2
           echo "（要改道请在项目内自行 cp 产物）" >&2; exit 2 ;;
    --selftest) SELFTEST=1; shift ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="${HERE}/vendor/build-timeline.mjs"
TOOLBOX_ROOT="${AGENT_TOOLBOX_HOME:-$(cd "${HERE}/../.." && pwd)}"
VOICE_VENDOR="${TOOLBOX_ROOT}/tools/voice-over-neural-tts/vendor"

if [[ $SELFTEST -eq 1 ]]; then
  echo "依赖检查:"
  for c in node uv ffmpeg ffprobe; do
    if command -v "$c" >/dev/null 2>&1; then
      echo "  ✓ $c"
    else
      echo "  ✗ $c 缺失"
      exit 1
    fi
  done
  echo "烟测通过：依赖齐备（配音需 voice-over-neural-tts 的 venv，本工具需在目标项目内运行）"
  exit 0
fi

if [[ -z "${PROJECT}" ]]; then
  echo "用法: toolbox run remotion-timeline-builder --in <Remotion 项目目录>" >&2
  exit 2
fi

[[ -f "${PROJECT}/package.json" ]] || {
  echo "目标目录不像 Remotion 项目（无 package.json）: ${PROJECT}" >&2
  exit 1
}

# vendor 脚本期望位于 <项目>/scripts/ 下，按此约定映射
if [[ ! -d "${PROJECT}/scripts" ]]; then
  echo "目标项目缺少 scripts/ 目录" >&2
  exit 1
fi

[[ -f "${VOICE_VENDOR}/synth.py" ]] || {
  echo "找不到配音脚本的唯一副本: ${VOICE_VENDOR}/synth.py" >&2
  echo "（它归工具箱里的 voice-over-neural-tts 工具所有，检查 AGENT_TOOLBOX_HOME 是否指对仓库根）" >&2
  exit 1
}

cp "${SCRIPT}" "${PROJECT}/scripts/build-timeline.mjs"
mkdir -p "${PROJECT}/scripts/voice"
cp "${VOICE_VENDOR}/synth.py" "${VOICE_VENDOR}/setup.sh" "${PROJECT}/scripts/voice/"
chmod +x "${PROJECT}/scripts/voice/setup.sh"
echo "已就位: ${PROJECT}/scripts/build-timeline.mjs + scripts/voice/"
echo "下一步: cd ${PROJECT} && bash scripts/voice/setup.sh && node scripts/build-timeline.mjs"
echo "  配音引擎细节见 toolbox 的 voice-over-neural-tts 工具"
echo "${PROJECT}/public/timeline.json"
