#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${HOME}/.config/cloudbridge"
CONFIG_FILE="${CONFIG_DIR}/env"
BIN_DIR="${HOME}/.local/bin"
VENV_DIR="${PROJECT_DIR}/.venv"

say() {
  printf '\n[CloudBridge setup] %s\n' "$*"
}

ask() {
  local prompt="$1"
  local default_value="${2:-}"
  local answer
  if [[ -n "${default_value}" ]]; then
    read -r -p "${prompt} [${default_value}]: " answer
    printf '%s' "${answer:-$default_value}"
  else
    read -r -p "${prompt}: " answer
    printf '%s' "$answer"
  fi
}

ask_secret() {
  local prompt="$1"
  local answer
  read -r -s -p "${prompt}: " answer
  printf '\n' >&2
  printf '%s' "$answer"
}

require_kali_tools() {
  say "Installing Kali system packages"
  sudo apt update
  sudo apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    python3-pyfuse3 \
    fuse3 \
    libfuse3-dev \
    pkg-config \
    thunar \
    exo-utils \
    xdg-utils \
    mousepad \
    ristretto \
    sqlite3
}

create_venv() {
  say "Creating Python virtual environment"
  python3 -m venv --system-site-packages "${VENV_DIR}"
  "${VENV_DIR}/bin/python" -m pip install --upgrade pip
  "${VENV_DIR}/bin/python" -m pip install -r "${PROJECT_DIR}/requirements.txt"
}

write_config() {
  local token="$1"
  local remote_root="$2"
  local local_path="$3"

  mkdir -p "${CONFIG_DIR}"
  {
    printf 'export YANDEX_TOKEN=%q\n' "${token}"
    printf 'export YANDEX_PATH=%q\n' "${remote_root}"
    printf 'export LOCAL_PATH=%q\n' "${local_path}"
    printf 'export CLOUDBRIDGE_IGNORE_FILE=%q\n' "${CONFIG_DIR}/ignored.json"
    printf 'export CLOUDBRIDGE_PROJECT_DIR=%q\n' "${PROJECT_DIR}"
    printf 'export CLOUDBRIDGE_PYTHON=%q\n' "${VENV_DIR}/bin/python"
    printf 'export PYTHONUNBUFFERED=1\n'
  } > "${CONFIG_FILE}"
  chmod 600 "${CONFIG_FILE}"
  mkdir -p "${local_path}" "${HOME}/.cache/cloudbridge/sessions"
}

install_thunar_action() {
  local local_path="$1"
  local remote_root="$2"

  say "Installing Thunar context menu action"
  "${VENV_DIR}/bin/python" "${PROJECT_DIR}/scratch/install_thunar_action.py" \
    --project-dir "${PROJECT_DIR}" \
    --local-path "${local_path}" \
    --remote-root "${remote_root}" \
    --env-file "${CONFIG_FILE}" \
    --python-bin "${VENV_DIR}/bin/python" \
    --editor auto
  thunar -q 2>/dev/null || true
}

install_launchers() {
  mkdir -p "${BIN_DIR}"
  cat > "${BIN_DIR}/cloudbridge-start" <<EOF
#!/usr/bin/env bash
set -euo pipefail
source "${CONFIG_FILE}"
cd "${PROJECT_DIR}"
exec "\${CLOUDBRIDGE_PYTHON}" -m src.main 2>&1 | tee /tmp/cloudbridge-daemon.log
EOF
  chmod +x "${BIN_DIR}/cloudbridge-start"

  cat > "${BIN_DIR}/cloudbridge-open" <<EOF
#!/usr/bin/env bash
set -euo pipefail
source "${CONFIG_FILE}"
cd "${PROJECT_DIR}"
exec "\${CLOUDBRIDGE_PYTHON}" -m src.cloud_open "\$@"
EOF
  chmod +x "${BIN_DIR}/cloudbridge-open"
}

main() {
  say "CloudBridge first-run setup for Kali"

  local default_local="${HOME}/Videos/copypapka"
  local default_remote="/CloudBridgeTest"

  local token
  local remote_root
  local local_path

  token="$(ask_secret "Yandex OAuth token")"
  remote_root="$(ask "Yandex.Disk folder to sync" "${default_remote}")"
  local_path="$(ask "Local folder shown in Thunar" "${default_local}")"

  require_kali_tools
  create_venv
  write_config "${token}" "${remote_root}" "${local_path}"
  install_thunar_action "${local_path}" "${remote_root}"
  install_launchers

  say "Setup complete"
  printf 'Config: %s\n' "${CONFIG_FILE}"
  printf 'Context menu: Thunar -> right click a file -> CloudBridge actions\n'
  printf 'Start watcher/daemon with: cloudbridge-start\n'
  printf 'Open folder with: thunar "%s"\n' "${local_path}"

  if [[ ":${PATH}:" != *":${BIN_DIR}:"* ]]; then
    printf '\nAdd this to your shell config if cloudbridge-start is not found:\n'
    printf 'export PATH="$HOME/.local/bin:$PATH"\n'
  fi

  read -r -p "Start CloudBridge daemon now? [Y/n]: " start_now
  if [[ "${start_now:-Y}" =~ ^[Yy]$ ]]; then
    exec "${BIN_DIR}/cloudbridge-start"
  fi
}

main "$@"
