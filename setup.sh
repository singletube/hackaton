#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${HOME}/.config/cloudbridge"
CONFIG_FILE="${CONFIG_DIR}/env"
BIN_DIR="${HOME}/.local/bin"
VENV_DIR="${PROJECT_DIR}/.venv"
CACHE_DIR="${HOME}/.cache/cloudbridge"
AUTO_YES=0
TARGET_OS=""

say() {
  printf '\n[CloudBridge setup] %s\n' "$*"
}

warn() {
  printf '[CloudBridge setup] %s\n' "$*" >&2
}

usage() {
  cat <<'EOF'
Usage: ./setup.sh [options]

Options:
  -y, --yes                 Auto-confirm package installation prompts
      --target kali|alt     Installation target
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
      --target)
        TARGET_OS="${2:-}"
        shift 2
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

ask_target_os() {
  local answer
  read -r -p "Install target [kali/alt] [kali]: " answer
  case "${answer:-kali}" in
    alt|ALT|Alt)
      printf 'alt'
      ;;
    *)
      printf 'kali'
      ;;
  esac
}

install_packages_kali() {
  local apt_flags=()
  if [[ ${AUTO_YES} -eq 1 ]]; then
    apt_flags+=("-y")
  fi

  say "Installing Kali system packages"
  sudo apt update
  sudo apt install "${apt_flags[@]}" \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    python3-pyfuse3 \
    attr \
    fuse3 \
    libfuse3-dev \
    pkg-config \
    thunar \
    desktop-file-utils \
    exo-utils \
    xdg-utils \
    zenity \
    mousepad \
    ristretto \
    sqlite3
}

install_packages_alt() {
  local apt_flags=()
  if [[ ${AUTO_YES} -eq 1 ]]; then
    apt_flags+=("-y")
  fi

  say "Installing ALT Linux system packages"
  sudo apt-get update
  sudo apt-get install "${apt_flags[@]}" \
    python3 \
    python3-module-pip \
    python3-module-pyfuse3 \
    python3-modules-sqlite3 \
    attr \
    fuse3 \
    libfuse3-devel \
    pkg-config \
    thunar \
    desktop-file-utils \
    xdg-utils \
    zenity \
    mousepad \
    ristretto \
    sqlite3
}

install_optional_desktop_packages() {
  local apt_bin="$1"
  local apt_flags=()
  if [[ ${AUTO_YES} -eq 1 ]]; then
    apt_flags+=("-y")
  fi

  say "Installing optional desktop helpers"
  local installed_any=0
  for package_name in xclip xsel wl-clipboard; do
    if sudo "${apt_bin}" install "${apt_flags[@]}" "${package_name}"; then
      installed_any=1
    else
      warn "Optional package ${package_name} was not installed"
    fi
  done
  if [[ ${installed_any} -eq 0 ]]; then
    warn "No optional clipboard helper was installed; share links will still be saved to ~/.cache/cloudbridge/last_share_link.txt"
  fi
}

install_best_effort_package() {
  local apt_bin="$1"
  local package_name="$2"
  local apt_flags=()
  if [[ ${AUTO_YES} -eq 1 ]]; then
    apt_flags+=("-y")
  fi

  if sudo "${apt_bin}" install "${apt_flags[@]}" "${package_name}"; then
    say "Installed optional package: ${package_name}"
  else
    warn "Optional package ${package_name} was not installed"
  fi
}

install_alt_filemanager_packages() {
  say "Installing optional ALT Linux file manager integration packages"
  install_best_effort_package apt-get nautilus
  install_best_effort_package apt-get nautilus-python
  install_best_effort_package apt-get python3-module-nautilus
}

create_venv() {
  say "Creating Python virtual environment"
  if ! python3 -m venv --help >/dev/null 2>&1; then
    warn "python3 -m venv is unavailable on this system"
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
  local db_path="${CACHE_DIR}/state.db"

  mkdir -p "${CONFIG_DIR}"
  mkdir -p "${CACHE_DIR}"
  {
    printf 'export YANDEX_TOKEN=%q\n' "${token}"
    printf 'export YANDEX_PATH=%q\n' "${remote_root}"
    printf 'export LOCAL_PATH=%q\n' "${local_path}"
    printf 'export CLOUDBRIDGE_IGNORE_FILE=%q\n' "${CONFIG_DIR}/ignored.json"
    printf 'export CLOUDBRIDGE_PROJECT_DIR=%q\n' "${PROJECT_DIR}"
    printf 'export CLOUDBRIDGE_PYTHON=%q\n' "${VENV_DIR}/bin/python"
    printf 'export CLOUDBRIDGE_DB_PATH=%q\n' "${db_path}"
    printf 'export CLOUDBRIDGE_REMOTE_POLL_INTERVAL=60\n'
    printf 'export CLOUDBRIDGE_TEXT_EDITOR=mousepad\n'
    printf 'export CLOUDBRIDGE_UNKNOWN_EDITOR=mousepad\n'
    printf 'export CLOUDBRIDGE_IMAGE_VIEWER=ristretto\n'
    printf 'export PYTHONUNBUFFERED=1\n'
  } > "${CONFIG_FILE}"
  chmod 600 "${CONFIG_FILE}"
  mkdir -p "${local_path}" "${CACHE_DIR}/sessions"
  touch "${db_path}"
  chmod 600 "${db_path}"
}

validate_config_input() {
  local token="$1"
  local remote_root="$2"
  local local_path="$3"

  if [[ -z "${token}" ]]; then
    warn "Yandex OAuth token is required"
    exit 1
  fi
  if [[ -z "${remote_root}" ]]; then
    warn "Yandex.Disk folder is required"
    exit 1
  fi
  if [[ -z "${local_path}" ]]; then
    warn "Local sync folder is required"
    exit 1
  fi
}

normalize_remote_root() {
  local remote_root="$1"
  remote_root="/${remote_root#/}"
  remote_root="${remote_root%/}"
  if [[ -z "${remote_root}" ]]; then
    remote_root="/"
  fi
  printf '%s' "${remote_root}"
}

ensure_user_path() {
  say "Ensuring ~/.local/bin is in PATH for future shells"
  mkdir -p "${BIN_DIR}"
  local line='export PATH="$HOME/.local/bin:$PATH"'
  for shell_file in "${HOME}/.profile" "${HOME}/.bashrc"; do
    touch "${shell_file}"
    if ! grep -Fxq "${line}" "${shell_file}"; then
      printf '\n%s\n' "${line}" >> "${shell_file}"
    fi
  done
}

install_thunar_integration() {
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

install_nautilus_integration() {
  say "Installing Nautilus context menu extension"
  "${VENV_DIR}/bin/python" "${PROJECT_DIR}/scratch/install_nautilus_extension.py" \
    --project-dir "${PROJECT_DIR}" \
    --python-bin "${VENV_DIR}/bin/python"
  nautilus -q 2>/dev/null || true
}

install_mime_opener() {
  say "Installing double-click placeholder opener"
  "${VENV_DIR}/bin/python" "${PROJECT_DIR}/scratch/install_mime_opener.py" \
    --project-dir "${PROJECT_DIR}" \
    --env-file "${CONFIG_FILE}" \
    --python-bin "${VENV_DIR}/bin/python" \
    --launcher "${BIN_DIR}/cloudbridge-open-or-default"
}

install_filemanager_integrations() {
  local local_path="$1"
  local remote_root="$2"

  thunar -q 2>/dev/null || true
  install_thunar_integration "${local_path}" "${remote_root}"
  install_nautilus_integration
  install_mime_opener
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

  cat > "${BIN_DIR}/cloudbridge-open-or-default" <<EOF
#!/usr/bin/env bash
set -euo pipefail
source "${CONFIG_FILE}"
cd "${PROJECT_DIR}"
exec "\${CLOUDBRIDGE_PYTHON}" -m src.open_or_default "\$@"
EOF
  chmod +x "${BIN_DIR}/cloudbridge-open-or-default"

  cat > "${BIN_DIR}/cloudbridge-store-local" <<EOF
#!/usr/bin/env bash
set -euo pipefail
source "${CONFIG_FILE}"
cd "${PROJECT_DIR}"
exec "\${CLOUDBRIDGE_PYTHON}" -m src.keep_local "\$@"
EOF
  chmod +x "${BIN_DIR}/cloudbridge-store-local"

  cat > "${BIN_DIR}/cloudbridge-restore-cloud" <<EOF
#!/usr/bin/env bash
set -euo pipefail
source "${CONFIG_FILE}"
cd "${PROJECT_DIR}"
exec "\${CLOUDBRIDGE_PYTHON}" -m src.restore_cloud "\$@"
EOF
  chmod +x "${BIN_DIR}/cloudbridge-restore-cloud"

  cat > "${BIN_DIR}/cloudbridge-share" <<EOF
#!/usr/bin/env bash
set -euo pipefail
source "${CONFIG_FILE}"
cd "${PROJECT_DIR}"
exec "\${CLOUDBRIDGE_PYTHON}" -m src.share_link "\$@"
EOF
  chmod +x "${BIN_DIR}/cloudbridge-share"
}

check_runtime_alt() {
  if ! command -v fusermount3 >/dev/null 2>&1; then
    warn "fusermount3 is not in PATH. FUSE mount may not work until fuse3 is installed correctly."
  fi
}

enable_fuse_allow_other() {
  say "Enabling FUSE allow_other support"
  if [[ ! -f /etc/fuse.conf ]]; then
    sudo touch /etc/fuse.conf
  fi

  if sudo grep -Eq '^\s*user_allow_other\s*$' /etc/fuse.conf; then
    return
  fi

  if sudo grep -Eq '^\s*#\s*user_allow_other\s*$' /etc/fuse.conf; then
    sudo sed -i 's/^\s*#\s*user_allow_other\s*$/user_allow_other/' /etc/fuse.conf
  else
    printf 'user_allow_other\n' | sudo tee -a /etc/fuse.conf >/dev/null
  fi
}

main() {
  parse_args "$@"
  normalize_line_endings

  if [[ -z "${TARGET_OS}" ]]; then
    TARGET_OS="$(ask_target_os)"
  fi

  local default_local="${HOME}/Videos/copypapka"
  local default_remote="/CloudBridgeTest"

  local token
  local remote_root
  local local_path

  token="$(ask_secret "Yandex OAuth token")"
  remote_root="$(ask "Yandex.Disk folder to sync" "${default_remote}")"
  local_path="$(ask "Local folder shown in Thunar" "${default_local}")"
  remote_root="$(normalize_remote_root "${remote_root}")"
  local_path="$(readlink -m "${local_path}")"
  validate_config_input "${token}" "${remote_root}" "${local_path}"

  case "${TARGET_OS}" in
    kali)
      say "CloudBridge first-run setup for Kali"
      install_packages_kali
      install_optional_desktop_packages apt
      ;;
    alt)
      say "CloudBridge first-run setup for ALT Linux"
      install_packages_alt
      install_optional_desktop_packages apt-get
      install_alt_filemanager_packages
      ;;
    *)
      warn "Unsupported target: ${TARGET_OS}"
      exit 1
      ;;
  esac

  create_venv
  write_config "${token}" "${remote_root}" "${local_path}"
  ensure_user_path
  install_launchers
  install_filemanager_integrations "${local_path}" "${remote_root}"
  enable_fuse_allow_other

  if [[ "${TARGET_OS}" == "alt" ]]; then
    check_runtime_alt
  fi

  say "Setup complete"
  printf 'Target OS: %s\n' "${TARGET_OS}"
  printf 'Config: %s\n' "${CONFIG_FILE}"
  printf 'Context menu: right click a file -> CloudBridge submenu (Thunar/Nautilus)\n'
  printf 'Double click: placeholder files open through CloudBridge automatically\n'
  printf 'Start watcher/daemon with: cloudbridge-start\n'
  printf 'Open folder with: thunar "%s"\n' "${local_path}"

  read -r -p "Start CloudBridge daemon now? [Y/n]: " start_now
  if [[ "${start_now:-Y}" =~ ^[Yy]$ ]]; then
    exec "${BIN_DIR}/cloudbridge-start"
  fi
}

main "$@"
