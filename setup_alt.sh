#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${HOME}/.config/cloudbridge"
CONFIG_FILE="${CONFIG_DIR}/env"
BIN_DIR="${HOME}/.local/bin"
VENV_DIR="${PROJECT_DIR}/.venv"
AUTO_YES=0

say() {
  printf '\n[CloudBridge ALT setup] %s\n' "$*"
}

warn() {
  printf '[CloudBridge ALT setup] %s\n' "$*" >&2
}

usage() {
  cat <<'EOF'
Usage: ./setup_alt.sh [options]

Options:
  -y, --yes                 Auto-confirm package installation prompts
  -h, --help                Show this help
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -y|--yes)
        AUTO_YES=1
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        warn "Unknown argument: $1"
        usage
        exit 1
        ;;
    esac
  done
}

normalize_line_endings() {
  say "Normalizing line endings for scripts copied from Windows"
  find "${PROJECT_DIR}" -type f \( -name "*.sh" -o -name "*.py" \) -exec sed -i 's/\r$//' {} +
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

require_alt_tools() {
  say "Installing ALT Linux system packages"
  local apt_flags=()
  if [[ ${AUTO_YES} -eq 1 ]]; then
    apt_flags+=("-y")
  fi

  sudo apt-get update
  sudo apt-get install "${apt_flags[@]}" \
    python3 \
    python3-module-pip \
    python3-module-pyfuse3 \
    python3-modules-sqlite3 \
    fuse3 \
    libfuse3-devel \
    pkg-config \
    thunar \
    xdg-utils \
    mousepad \
    ristretto \
    sqlite3
}

create_venv() {
  say "Creating Python virtual environment"
  if ! python3 -m venv --help >/dev/null 2>&1; then
    warn "python3 -m venv is unavailable on this ALT Linux system"
    warn "Install the package that provides the venv module and rerun setup_alt.sh"
    exit 1
  fi

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

check_runtime() {
  if ! command -v fusermount3 >/dev/null 2>&1; then
    warn "fusermount3 is not in PATH. FUSE mount may not work until fuse3 is installed correctly."
  fi

  if [[ -f /etc/fuse.conf ]] && ! grep -Eq '^\s*user_allow_other\s*$' /etc/fuse.conf; then
    warn "allow_other may require enabling user_allow_other in /etc/fuse.conf"
  fi
}

main() {
  say "CloudBridge first-run setup for ALT Linux"
  parse_args "$@"
  normalize_line_endings

  local default_local="${HOME}/Videos/copypapka"
  local default_remote="/CloudBridgeTest"

  local token
  local remote_root
  local local_path

  token="$(ask_secret "Yandex OAuth token")"
  remote_root="$(ask "Yandex.Disk folder to sync" "${default_remote}")"
  local_path="$(ask "Local folder shown in Thunar" "${default_local}")"

  require_alt_tools
  create_venv
  write_config "${token}" "${remote_root}" "${local_path}"
  install_thunar_action "${local_path}" "${remote_root}"
  install_launchers
  check_runtime

  say "Setup complete"
  printf 'Config: %s\n' "${CONFIG_FILE}"
  printf 'Context menu: Thunar -> right click a file -> Open with CloudBridge / Store Locally / Restore to Cloud\n'
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
