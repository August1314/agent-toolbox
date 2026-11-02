#!/usr/bin/env bash
# adapter.sh —— voice-over-neural-tts 的薄适配层
#
# 契约：
#   toolbox run voice-over-neural-tts --text "旁白文本" --out /path/seg-00.wav \
#          [--engine auto|edge|melo] [--voice zh-CN-YunxiNeural] [--rate=-10%] [--pitch=-2Hz] [--pause 0.30]
#   → stdout 一行 JSON：{"durationSec":..,"engine":..,"sentences":[{text,startSec,endSec,engine},..]}
#
#   首次使用先：adapter.sh --setup   （建 venv + 下离线兜底模型，约 1 分钟）
#
# vendor/ 里的两个脚本原样搬自 expression-video 实战工程（验证跑通后归位），
# 逻辑一个字没改。所有路径映射在本文件完成。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export VOICE_HOME="$HERE"
export VOICE_PY="${VOICE_PY:-$HERE/.venv-voice/bin/python}"
export MELO_MODEL_DIR="${MELO_MODEL_DIR:-$HERE/.voice-models/vits-melo-tts-zh_en}"

case "${1:-}" in
  --setup)
    exec bash "$HERE/vendor/setup.sh"
    ;;
  --selftest)
    echo "依赖检查:"
    for c in ffmpeg ffprobe uv; do
      command -v "$c" >/dev/null 2>&1 && echo "  ✓ $c" || echo "  ✗ $c (缺)"
    done
    if [[ -x "$VOICE_PY" ]]; then echo "  ✓ venv: $VOICE_PY"; else echo "  ✗ venv 未建，跑 --setup"; exit 1; fi
    "$VOICE_PY" -c "import edge_tts, sherpa_onnx" 2>/dev/null \
      && echo "  ✓ edge-tts + sherpa-onnx 可 import" || { echo "  ✗ 后端包缺失"; exit 1; }
    [[ -f "$MELO_MODEL_DIR/model.onnx" ]] && echo "  ✓ 离线兜底模型就位" || echo "  ✗ 缺兜底模型 (--setup 会下)"
    exit 0
    ;;
esac

ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --text)   ARGS+=("--text=$2"); shift 2 ;;
    --out)    ARGS+=("--out=$2"); shift 2 ;;
    --engine) ARGS+=("--engine=$2"); shift 2 ;;
    --voice)  ARGS+=("--voice=$2"); shift 2 ;;
    --rate)   ARGS+=("--rate=$2"); shift 2 ;;
    --pitch)  ARGS+=("--pitch=$2"); shift 2 ;;
    --pause)  ARGS+=("--pause=$2"); shift 2 ;;
    --text=*|--out=*|--engine=*|--voice=*|--rate=*|--pitch=*|--pause=*)
      # argparse 要求 --opt=value 形式：裸 "-10%" 会被当成选项名
      ARGS+=("$1"); shift ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

[[ ${#ARGS[@]} -gt 0 ]] || { echo "用法: adapter.sh --text <旁白> --out <wav> [--engine auto|edge|melo]" >&2; exit 2; }
exec "$VOICE_PY" "$HERE/vendor/synth.py" "${ARGS[@]}"
