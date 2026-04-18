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
YANDEX_CLIENT_ID=""
YANDEX_CLIENT_SECRET=""
NEXTCLOUD_URL=""
NEXTCLOUD_USERNAME=""
NEXTCLOUD_PASSWORD=""
INSTALL_SERVICE=1

usage() {
  cat <<'EOF'
Usage: install-linux.sh [options]

Options:
  --provider <name>         Cloud provider. Default: yandex
  --token <token>           Yandex Disk token
  --yandex-client-id <id>   Yandex OAuth application Client ID
  --yandex-client-secret <s> Yandex OAuth application Client secret
  --nextcloud-url <url>     Nextcloud server URL
  --nextcloud-username <u>  Nextcloud username
  --nextcloud-password <p>  Nextcloud app password
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
    --yandex-client-id)
      YANDEX_CLIENT_ID="$2"
      shift 2
      ;;
    --yandex-client-secret)
      YANDEX_CLIENT_SECRET="$2"
      shift 2
      ;;
    --nextcloud-url)
      NEXTCLOUD_URL="$2"
      shift 2
      ;;
    --nextcloud-username)
      NEXTCLOUD_USERNAME="$2"
      shift 2
      ;;
    --nextcloud-password)
      NEXTCLOUD_PASSWORD="$2"
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

if [[ "$PROVIDER" == "yandex" && -z "$TOKEN" && ( -z "$YANDEX_CLIENT_ID" || -z "$YANDEX_CLIENT_SECRET" ) ]]; then
  echo "provider=yandex requires either --token or both --yandex-client-id and --yandex-client-secret" >&2
  exit 1
fi

if [[ "$PROVIDER" == "nextcloud" && -z "$NEXTCLOUD_URL" ]]; then
  echo "--nextcloud-url is required for provider=nextcloud" >&2
  exit 1
fi

if [[ "$PROVIDER" == "nextcloud" && ( ( -n "$NEXTCLOUD_USERNAME" && -z "$NEXTCLOUD_PASSWORD" ) || ( -z "$NEXTCLOUD_USERNAME" && -n "$NEXTCLOUD_PASSWORD" ) ) ]]; then
  echo "--nextcloud-username and --nextcloud-password must be provided together" >&2
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
export CLOUDBRIDGE_CONFIG=$(printf '%q' "$APP_HOME/config.json")
export CLOUDBRIDGE_SYNC_ROOT=$(printf '%q' "$SYNC_ROOT")
export CLOUDBRIDGE_PROVIDER=$(printf '%q' "$PROVIDER")
export CLOUDBRIDGE_IMPORT_ROOT=$(printf '%q' "$IMPORT_ROOT")
export CLOUDBRIDGE_IMPORT_LAYOUT=$(printf '%q' "$IMPORT_LAYOUT")
EOF

if [[ -n "$TOKEN" ]]; then
  cat >>"$WRAPPER_PATH" <<EOF
export YANDEX_DISK_TOKEN=$(printf '%q' "$TOKEN")
EOF
fi

if [[ -n "$YANDEX_CLIENT_ID" ]]; then
  cat >>"$WRAPPER_PATH" <<EOF
export YANDEX_CLIENT_ID=$(printf '%q' "$YANDEX_CLIENT_ID")
EOF
fi

if [[ -n "$YANDEX_CLIENT_SECRET" ]]; then
  cat >>"$WRAPPER_PATH" <<EOF
export YANDEX_CLIENT_SECRET=$(printf '%q' "$YANDEX_CLIENT_SECRET")
EOF
fi

if [[ -n "$NEXTCLOUD_URL" ]]; then
  cat >>"$WRAPPER_PATH" <<EOF
export NEXTCLOUD_URL=$(printf '%q' "$NEXTCLOUD_URL")
EOF
fi

if [[ -n "$NEXTCLOUD_USERNAME" ]]; then
  cat >>"$WRAPPER_PATH" <<EOF
export NEXTCLOUD_USERNAME=$(printf '%q' "$NEXTCLOUD_USERNAME")
EOF
fi

if [[ -n "$NEXTCLOUD_PASSWORD" ]]; then
  cat >>"$WRAPPER_PATH" <<EOF
export NEXTCLOUD_PASSWORD=$(printf '%q' "$NEXTCLOUD_PASSWORD")
EOF
fi

cat >>"$WRAPPER_PATH" <<EOF
exec $(printf '%q' "$INSTALL_ROOT/venv/bin/cloudbridge") "\$@"
EOF
chmod +x "$WRAPPER_PATH"

if [[ "$PROVIDER" == "yandex" && -z "$TOKEN" && -n "$YANDEX_CLIENT_ID" && -n "$YANDEX_CLIENT_SECRET" ]]; then
  "$WRAPPER_PATH" setup-yandex --client-id "$YANDEX_CLIENT_ID" --client-secret "$YANDEX_CLIENT_SECRET"
fi

if [[ "$PROVIDER" == "nextcloud" && -n "$NEXTCLOUD_URL" && ( -z "$NEXTCLOUD_USERNAME" || -z "$NEXTCLOUD_PASSWORD" ) ]]; then
  "$WRAPPER_PATH" setup-nextcloud --server "$NEXTCLOUD_URL"
fi

DESKTOP_SETUP_ARGS=(desktop-setup --manager "$MANAGER" --launcher-command "$WRAPPER_PATH" --service-name "$SERVICE_NAME")
if [[ "$INSTALL_SERVICE" -eq 0 ]]; then
  DESKTOP_SETUP_ARGS+=(--skip-service)
fi
"$WRAPPER_PATH" "${DESKTOP_SETUP_ARGS[@]}"

if [[ "$INSTALL_SERVICE" -eq 1 ]]; then
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

EOF

if [[ "$PROVIDER" == "nextcloud" && -n "$NEXTCLOUD_URL" && -z "$NEXTCLOUD_USERNAME" && -z "$NEXTCLOUD_PASSWORD" ]]; then
  cat <<EOF
nextcloud_setup=browser-login
EOF
fi

if [[ "$PROVIDER" == "yandex" && -z "$TOKEN" && -n "$YANDEX_CLIENT_ID" && -n "$YANDEX_CLIENT_SECRET" ]]; then
  cat <<EOF
yandex_setup=device-code
EOF
fi

cat <<EOF

Make sure ~/.local/bin is in PATH.
EOF
