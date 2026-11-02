#!/usr/bin/env bash
# adapter.sh —— remotion-timeline-builder 的薄适配层
#
# 契约：toolbox run remotion-timeline-builder --in <项目目录> --out <timeline.json>
#
# vendor/build-timeline.mjs 原样：它是从 expression-video 项目里验证跑通的脚本，
# 逻辑一个字没改。所有路径映射在本文件完成。

set -euo pipefail

PROJECT=""
SELFTEST=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --in) PROJECT="$2"; shift 2 ;;
    --out) PROJECT_PARENT="$(dirname "$2")"; shift 2 ;;
    --selftest) SELFTEST=1; shift ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="${HERE}/vendor/build-timeline.mjs"

if [[ $SELFTEST -eq 1 ]]; then
  echo "依赖检查:"
  for c in node say ffprobe ffmpeg; do
    if command -v "$c" >/dev/null 2>&1; then
      echo "  ✓ $c"
    else
      echo "  ✗ $c 缺失"
      exit 1
    fi
  done
  echo "烟测通过：依赖齐备（本工具需在目标项目内运行，不做端到端渲染）"
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

cp "${SCRIPT}" "${PROJECT}/scripts/build-timeline.mjs"
echo "已就位: ${PROJECT}/scripts/build-timeline.mjs"
echo "下一步: cd ${PROJECT} && node scripts/build-timeline.mjs"
echo "${PROJECT}/public/timeline.json"
