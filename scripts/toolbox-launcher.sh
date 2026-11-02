#!/usr/bin/env bash
# toolbox CLI 启动器模板 —— 由 install.sh 复制到 ~/.local/bin/toolbox
# __REPO_ROOT__ 会被替换为实际的仓库路径。
#
# 保持这个文件与 install.sh 解耦：改启动逻辑只动这里。

export AGENT_TOOLBOX_HOME="${AGENT_TOOLBOX_HOME:-__REPO_ROOT__}"
export PYTHONPATH="${AGENT_TOOLBOX_HOME}${PYTHONPATH:+:${PYTHONPATH}}"
exec python3 -m toolbox "$@"
