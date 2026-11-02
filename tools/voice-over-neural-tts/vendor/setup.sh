#!/usr/bin/env bash
# setup.sh — 配音环境(幂等,可重复跑)
#
# 装两样东西:
#   .venv-voice/   Python 3.11 + edge-tts(在线主后端)+ sherpa-onnx(离线兜底)
#                  选 3.11 是因为 sherpa-onnx 的 wheel 只覆盖到 3.12,
#                  系统 python 是 3.14 → 装不上。
#   .voice-models/ MeloTTS zh_en 模型(MIT,159MB,离线兜底用)
#
# 模型不进 git(.gitignore 已排除),成片用的 WAV 进 git ——
# 所以【渲染永远离线】,只有重录音色时才需要网络。
set -euo pipefail
# 装到哪:默认工程根;工具库里复用时用 VOICE_HOME 指到工具目录
REPO="${VOICE_HOME:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
VENV="$REPO/.venv-voice"
MODELS="$REPO/.voice-models"
MELO_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-melo-tts-zh_en.tar.bz2"

command -v uv >/dev/null || { echo "✗ 需要 uv(brew install uv)"; exit 1; }
command -v ffmpeg >/dev/null || { echo "✗ 需要 ffmpeg"; exit 1; }

if [ ! -x "$VENV/bin/python" ]; then
  echo "→ 建 venv(Python 3.11)"
  uv venv "$VENV" --python 3.11 -q
fi
echo "→ 装 edge-tts / sherpa-onnx"
uv pip install --python "$VENV/bin/python" -q edge-tts sherpa-onnx

mkdir -p "$MODELS"
if [ ! -f "$MODELS/vits-melo-tts-zh_en/model.onnx" ]; then
  echo "→ 下 Melo 兜底模型(159MB,首次约 1 分钟)"
  curl -sL --retry 3 -o "$MODELS/melo.tar.bz2" "$MELO_URL"
  tar xjf "$MODELS/melo.tar.bz2" -C "$MODELS"
  rm -f "$MODELS/melo.tar.bz2"
fi

"$VENV/bin/python" - <<'PY'
import importlib.metadata as m
print(f"✓ edge-tts {m.version('edge-tts')} / sherpa-onnx {m.version('sherpa-onnx')}")
PY
echo "✓ 配音环境就绪:$VENV"
