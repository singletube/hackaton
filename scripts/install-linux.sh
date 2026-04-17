#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

INSTALL_ROOT="${HOME}/.local/share/cloudbridge/app"
BIN_DIR="${HOME}/.local/bin"
WRAPPER_PATH="${BIN_DIR}/cloudbridge-local"
SERVICE_NAME="cloudbridge"
MANAGER="auto"
PROVIDER="yandex"
SYNC_ROOT="${HOME}/CloudBridge"
IMPORT_ROOT="/incoming"
IMPORT_LAYOUT="flat"
APP_HOME="${HOME}/.local/share/cloudbridge"
TOKEN=""
INSTALL_SERVICE=1

usage() {
  cat <<'EOF'
Usage: install-linux.sh [options]

Options:
  --provider <name>         Cloud provider. Default: yandex
  --token <token>           Yandex Disk token
  --sync-root <path>        Local sync root. Default: ~/CloudBridge
  --import-root <path>      Remote import root for external files. Default: /incoming
  --import-layout <layout>  External import layout: flat, by-parent, by-date. Default: flat
  --manager <name>          File manager backend: auto, nautilus, thunar, nemo, caja. Default: auto
  --service-name <name>     systemd --user service name. Default: cloudbridge
  --skip-service            Do not install or enable the systemd user service
  --install-root <path>     Venv install root. Default: ~/.local/share/cloudbridge/app
  --app-home <path>         App state root. Default: ~/.local/share/cloudbridge
  --wrapper-path <path>     Wrapper binary path. Default: ~/.local/bin/cloudbridge-local
  --help                    Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --provider)
      PROVIDER="$2"
      shift 2
      ;;
    --token)
      TOKEN="$2"
      shift 2
      ;;
    --sync-root)
      SYNC_ROOT="$2"
      shift 2
      ;;
    --import-root)
      IMPORT_ROOT="$2"
      shift 2
      ;;
    --import-layout)
      IMPORT_LAYOUT="$2"
      shift 2
      ;;
    --manager)
      MANAGER="$2"
      shift 2
      ;;
    --service-name)
      SERVICE_NAME="$2"
      shift 2
      ;;
    --skip-service)
      INSTALL_SERVICE=0
      shift
      ;;
    --install-root)
      INSTALL_ROOT="$2"
      shift 2
      ;;
    --app-home)
      APP_HOME="$2"
      shift 2
      ;;
    --wrapper-path)
      WRAPPER_PATH="$2"
      shift 2
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required" >&2
  exit 1
fi

if [[ "$PROVIDER" == "yandex" && -z "$TOKEN" ]]; then
  echo "--token is required for provider=yandex" >&2
  exit 1
fi

mkdir -p "$INSTALL_ROOT" "$APP_HOME" "$BIN_DIR" "$SYNC_ROOT"

python3 -m venv "$INSTALL_ROOT/venv"
"$INSTALL_ROOT/venv/bin/python" -m pip install --upgrade pip
"$INSTALL_ROOT/venv/bin/python" -m pip install "$REPO_ROOT"

cat >"$WRAPPER_PATH" <<EOF
#!/usr/bin/env bash
set -euo pipefail
export CLOUDBRIDGE_HOME=$(printf '%q' "$APP_HOME")
export CLOUDBRIDGE_SYNC_ROOT=$(printf '%q' "$SYNC_ROOT")
export CLOUDBRIDGE_PROVIDER=$(printf '%q' "$PROVIDER")
export CLOUDBRIDGE_IMPORT_ROOT=$(printf '%q' "$IMPORT_ROOT")
export CLOUDBRIDGE_IMPORT_LAYOUT=$(printf '%q' "$IMPORT_LAYOUT")
export YANDEX_DISK_TOKEN=$(printf '%q' "$TOKEN")
exec $(printf '%q' "$INSTALL_ROOT/venv/bin/cloudbridge") "\$@"
EOF
chmod +x "$WRAPPER_PATH"

"$WRAPPER_PATH" init
"$WRAPPER_PATH" install-filemanager --manager "$MANAGER" --launcher-command "$WRAPPER_PATH"

if [[ "$INSTALL_SERVICE" -eq 1 ]]; then
  "$WRAPPER_PATH" install-service --service-name "$SERVICE_NAME" --launcher-command "$WRAPPER_PATH"
  if command -v systemctl >/dev/null 2>&1; then
    if systemctl --user daemon-reload && systemctl --user enable --now "${SERVICE_NAME}.service"; then
      SERVICE_STATUS="enabled"
    else
      SERVICE_STATUS="installed"
    fi
  else
    SERVICE_STATUS="installed"
  fi
else
  SERVICE_STATUS="skipped"
fi

cat <<EOF
installed=true
wrapper=$WRAPPER_PATH
sync_root=$SYNC_ROOT
app_home=$APP_HOME
provider=$PROVIDER
import_root=$IMPORT_ROOT
import_layout=$IMPORT_LAYOUT
service=$SERVICE_NAME
service_status=$SERVICE_STATUS

Make sure ~/.local/bin is in PATH.
EOF
