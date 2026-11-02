#!/usr/bin/env bash
# install.sh —— 把工具箱挂接到本机各 agent。
#
# 只建软链，不复制文件。复制必然导致版本漂移。
# 用法：
#   ./install.sh              # 安装并挂接
#   ./install.sh --uninstall  # 移除挂接

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOME_DIR="${HOME}"
SKILL_NAME="reuse-first"
SRC_SKILL="${REPO_ROOT}/skills/${SKILL_NAME}"
LAUNCHER_SRC="${REPO_ROOT}/scripts/toolbox-launcher.sh"

BIN_DIR="${HOME_DIR}/.local/bin"
MOUNT_TARGETS=(
  "${HOME_DIR}/.agents/skills"
  "${HOME_DIR}/.claude/skills"
  "${HOME_DIR}/.codex/skills"
  "${HOME_DIR}/.workbuddy/skills"
  "${HOME_DIR}/.gemini/skills"
  "${HOME_DIR}/.config/opencode/skills"
)

info() { printf '  %s\n' "$*"; }
ok()   { printf 'ok  %s\n' "$*"; }
warn() { printf 'warn  %s\n' "$*"; }

if [[ "${1:-}" == "--uninstall" ]]; then
  echo "移除挂接:"
  for d in "${MOUNT_TARGETS[@]}"; do
    link="${d}/${SKILL_NAME}"
    if [[ -L "${link}" ]]; then
      rm "${link}"
      ok "removed ${link}"
    fi
  done
  if [[ -f "${BIN_DIR}/toolbox" ]]; then
    rm "${BIN_DIR}/toolbox"
    ok "removed ${BIN_DIR}/toolbox"
  fi
  exit 0
fi

echo "工具箱: ${REPO_ROOT}"

# 1. CLI 上 PATH
echo
echo "安装 CLI:"
mkdir -p "${BIN_DIR}"
python3 - "${LAUNCHER_SRC}" "${BIN_DIR}/toolbox" "${REPO_ROOT}" <<'PATCHER'
import sys
src, dst, repo = sys.argv[1], sys.argv[2], sys.argv[3]
with open(src, "r", encoding="utf-8") as f:
    body = f.read()
with open(dst, "w", encoding="utf-8") as f:
    f.write(body.replace("__REPO_ROOT__", repo))
PATCHER
chmod +x "${BIN_DIR}/toolbox"
ok "${BIN_DIR}/toolbox"

# 2. skill 挂接
echo
echo "挂接 skill 到各 agent:"
for d in "${MOUNT_TARGETS[@]}"; do
  mkdir -p "${d}"
  link="${d}/${SKILL_NAME}"
  if [[ -e "${link}" && ! -L "${link}" ]]; then
    warn "${link} 已存在且不是软链，跳过"
    continue
  fi
  rm -f "${link}"
  ln -s "${SRC_SKILL}" "${link}"
  ok "${link} -> ${SRC_SKILL}"
done

# 3. PATH 提示
echo
case ":${PATH}:" in
  *":${BIN_DIR}:"*)
    info "PATH 已包含 ${BIN_DIR}"
    ;;
  *)
    warn "${BIN_DIR} 不在 PATH 中，请加入 shell 配置："
    info "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc"
    ;;
esac

echo
ok "安装完成。测试: toolbox probe"
