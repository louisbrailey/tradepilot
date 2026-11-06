#!/usr/bin/env bash
# Run once on a fresh Ubuntu 24.04 x86_64 server after Tailscale/Ollama setup.
# Stages software only. Does not transfer credentials, enable the gateway or alter the Mac.
set -euo pipefail
if [[ $(uname -s) != Linux || $(uname -m) != x86_64 || $EUID != 0 ]]; then
  echo 'Requires root on the new Ubuntu 24.04 x86_64 server.' >&2; exit 1
fi
source /etc/os-release
if [[ $ID != ubuntu || $VERSION_ID != 24.04 ]]; then
  echo 'This installer targets Ubuntu 24.04 only.' >&2; exit 1
fi
if [[ -e /opt/tradepilot || -L /opt/tradepilot || -e /var/lib/tradepilot || -L /var/lib/tradepilot ]]; then
  echo 'Existing installation/state found; preserve it and use a reviewed upgrade.' >&2; exit 1
fi
command -v tailscale >/dev/null
command -v ollama >/dev/null
systemctl cat tailscaled.service >/dev/null
systemctl cat ollama.service >/dev/null
SOURCE=$(cd "$(dirname "$0")/../.." && pwd)
test -f "$SOURCE/BACKTEST-SUMMARY.json"
test -f "$SOURCE/server/inference_guard.py"
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv git ca-certificates
useradd --system --user-group --home-dir /var/lib/tradepilot --shell /usr/sbin/nologin tradepilot
install -d -m 0755 /opt/tradepilot/app /opt/tradepilot/app/scripts
install -d -m 0700 -o tradepilot -g tradepilot /var/lib/tradepilot /var/lib/tradepilot/private /var/lib/tradepilot/private/runtime
cp -R "$SOURCE/server" /opt/tradepilot/app/
cp "$SOURCE/BACKTEST-SUMMARY.json" /opt/tradepilot/app/
install -m 0644 "$SOURCE/scripts/remote-gateway.py" "$SOURCE/scripts/pair-local-server.py" /opt/tradepilot/app/scripts/
install -m 0644 "$SOURCE/deploy/remote/cache-models.py" /opt/tradepilot/app/scripts/
python3 -m venv /opt/tradepilot/venv
/opt/tradepilot/venv/bin/pip install -r "$SOURCE/server/requirements.txt"
git clone https://github.com/shiyu-coder/Kronos.git /opt/tradepilot/kronos
git -C /opt/tradepilot/kronos checkout --detach 67b630e67f6a18c9e9be918d9b4337c960db1e9a
python3 -m venv /opt/tradepilot/kronos-venv
# CPU wheels avoid unnecessary CUDA dependencies on this CPU-only host.
/opt/tradepilot/kronos-venv/bin/pip install 'torch==2.14.0' --index-url https://download.pytorch.org/whl/cpu
/opt/tradepilot/kronos-venv/bin/pip install -r "$SOURCE/deploy/remote/model-requirements.txt"
/opt/tradepilot/kronos-venv/bin/python -c 'import torch, pandas, numpy, einops, huggingface_hub; assert torch.version.cuda is None'
runuser -u tradepilot -- env HOME=/var/lib/tradepilot HF_HUB_DISABLE_TELEMETRY=1 \
  /opt/tradepilot/kronos-venv/bin/python /opt/tradepilot/app/scripts/cache-models.py
install -d -m 0755 /etc/systemd/system/ollama.service.d
install -m 0644 "$SOURCE/deploy/remote/ollama-override.conf" /etc/systemd/system/ollama.service.d/tradepilot.conf
install -m 0644 "$SOURCE"/deploy/remote/tradepilot*.service "$SOURCE"/deploy/remote/tradepilot*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl restart ollama
OLLAMA_HOST=127.0.0.1:11434 ollama pull qwen3.5:4b
# Record exact installed distributions/model identity on the server, not in source.
/opt/tradepilot/venv/bin/pip freeze > /opt/tradepilot/backend-installed.txt
/opt/tradepilot/kronos-venv/bin/pip freeze > /opt/tradepilot/models-installed.txt
OLLAMA_HOST=127.0.0.1:11434 ollama list > /opt/tradepilot/ollama-installed.txt
echo 'Staged only. Gateway and backup timer are NOT enabled. Follow REMOTE-SETUP.md for verification and cutover.'
