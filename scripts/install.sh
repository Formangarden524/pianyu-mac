#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if [ "$(uname -s)" != Darwin ] || [ "$(uname -m)" != arm64 ]; then echo '需要 Apple Silicon Mac，请使用原生终端（关闭 Rosetta）。'; exit 1; fi
mac_major="$(sw_vers -productVersion | cut -d. -f1)"
if [ "$mac_major" -lt 15 ]; then echo '本发行版要求 macOS 15 或以上。'; exit 1; fi
py="${VIDEO_AGENT_PYTHON:-$(command -v python3.12 || true)}"
if [ -z "$py" ]; then echo '请先安装 Python 3.12：https://www.python.org/downloads/macos/ 或 brew install python@3.12'; exit 1; fi
"$py" -c 'import sys,platform; assert sys.version_info[:2]==(3,12) and platform.machine()=="arm64", "需要原生 arm64 Python 3.12"'
[ -x .venv-video/bin/python ] || "$py" -m venv .venv-video
.venv-video/bin/python -m pip install -r configs/video-agent-requirements.lock.txt
.venv-video/bin/python -m pip check
.venv-video/bin/python -c 'import mlx.core,mlx_whisper,fastapi,httpx,psutil,imageio_ffmpeg,opencc; from PIL import Image'
echo '依赖安装完成。下一步双击 02-下载模型.command。'
