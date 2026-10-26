#!/usr/bin/env bash
# Prepara o Ubuntu do WSL para desenvolvimento de IA usando o acervo do SSD (/mnt/a).
# Rode dentro do Linux:  bash /mnt/a/linux/configurar-ubuntu.sh
set -euo pipefail

SSD=/mnt/a
echo "== Pacotes basicos =="
sudo apt-get update
sudo apt-get install -y build-essential cmake git curl wget pkg-config libcurl4-openssl-dev python3-venv unzip

echo "== GPU =="
if nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,memory.total --format=csv
else
  echo "GPU nao visivel no Linux: atualize o driver NVIDIA no Windows e rode 'wsl --update'."
fi

echo "== llama.cpp para Linux (do instalador guardado no SSD) =="
mkdir -p "$HOME/ia/llama.cpp"
pacote=$(ls "$SSD"/motores/llama.cpp-outras-maquinas/*/llama-*-bin-ubuntu-cuda-*-x64.tar.gz 2>/dev/null | sort | tail -n 1 || true)
if [ -n "$pacote" ]; then
  tar -xzf "$pacote" -C "$HOME/ia/llama.cpp" --strip-components=1
  cudart=$(ls "$(dirname "$pacote")"/cudart-llama-*-ubuntu-cuda-*-x64.tar.gz 2>/dev/null | tail -n 1 || true)
  [ -n "$cudart" ] && tar -xzf "$cudart" -C "$HOME/ia/llama.cpp" --strip-components=1
  echo "Instalado em ~/ia/llama.cpp (ex.: ~/ia/llama.cpp/llama-server -m $SSD/modelos/llm/gemma-4-12b/gemma-4-12b-it-qat-q4_0.gguf)"
else
  echo "Instalador nao encontrado. No Windows rode: A:\\scripts\\instalar-motores.ps1 -Motor llama.cpp-outras-maquinas"
fi

echo "== uv (Python) =="
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi

cat <<'FIM'

Pronto. Dicas:
  - Modelos do acervo: /mnt/a/modelos   (ler do NTFS e mais lento; para treino, copie para ~/)
  - Treino de LoRA:    cd /mnt/a/dev/lora && uv run treinar-lora.py --help
FIM
