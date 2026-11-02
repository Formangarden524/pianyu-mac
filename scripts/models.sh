#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
export OLLAMA_HOST=127.0.0.1:11434
ollama_cli="$(command -v ollama || true)"
if [ -z "$ollama_cli" ] && [ -x /Applications/Ollama.app/Contents/Resources/ollama ]; then ollama_cli=/Applications/Ollama.app/Contents/Resources/ollama; fi
if [ -z "$ollama_cli" ]; then echo '请先安装并打开官方 Ollama：https://ollama.com/download/mac'; exit 1; fi
[ -x .venv-video/bin/python ] || { echo '请先安装依赖'; exit 1; }
.venv-video/bin/python - <<'PY'
import httpx,re
try:
 r=httpx.get('http://127.0.0.1:11434/api/version',trust_env=False,timeout=5);r.raise_for_status()
 v=tuple(map(int,re.findall(r'\d+',r.json()['version'])[:3]))
 assert v>=(0,12,7),'请升级 Ollama 至0.12.7或更新版本'
except Exception as e:raise SystemExit('请先打开/更新 Ollama。'+str(e))
PY
echo '1）Qwen3-VL 8B：约6.2GB，建议16GB及以上内存，试用档（尚未实机验收）'
echo '2）Qwen3-VL 30B：约20GB，建议32GB及以上，64GB更从容'
read -r -p '请选择 [1/2，默认1]：' choice
case "${choice:-1}" in 1) model=qwen3-vl:8b-instruct;; 2) model=qwen3-vl:30b-a3b-instruct;; *) echo '无效选择'; exit 1;; esac
"$ollama_cli" pull "$model"
mkdir -p outputs
printf 'FROM %s\nPARAMETER num_ctx 8192\nPARAMETER temperature 0.1\nSYSTEM "默认使用简体中文，忠实于材料，不编造。"\n' "$model" > outputs/Modelfile.pianyu
"$ollama_cli" create pianyu-instruct -f outputs/Modelfile.pianyu
.venv-video/bin/python - <<'PY'
from pathlib import Path
from huggingface_hub import snapshot_download
snapshot_download('mlx-community/whisper-small-mlx',local_dir='runtimes/whisper-small-mlx',allow_patterns=['config.json','weights.npz','*.safetensors'])
p=Path('runtimes/whisper-small-mlx');assert (p/'config.json').exists() and any((p/n).exists() for n in ['weights.npz','weights.safetensors']),'Whisper权重不完整'
print('模型准备完成。下一步启动工作台。')
PY
