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
ALLOW_ROOT=0
NO_BROWSER=0

usage() {
  cat <<'EOF'
Использование: install-linux.sh [опции]

Опции:
  --provider <name>          Провайдер облака. По умолчанию: yandex
  --token <token>            Токен Яндекс Диска
  --yandex-client-id <id>    Client ID OAuth-приложения Яндекса
  --yandex-client-secret <s> Client secret OAuth-приложения Яндекса
  --nextcloud-url <url>      Адрес сервера Nextcloud
  --nextcloud-username <u>   Имя пользователя Nextcloud
  --nextcloud-password <p>   Пароль приложения Nextcloud
  --sync-root <path>         Локальная папка синхронизации. По умолчанию: ~/CloudBridge
  --import-root <path>       Облачная папка для внешнего импорта. По умолчанию: /incoming
  --import-layout <layout>   Схема внешнего импорта: flat, by-parent, by-date. По умолчанию: flat
  --manager <name>           Файловый менеджер: auto, nautilus, thunar, nemo, caja. По умолчанию: auto
  --service-name <name>      Имя службы systemd --user. По умолчанию: cloudbridge
  --skip-service             Не устанавливать и не включать пользовательскую службу systemd
  --no-browser               Не пытаться открывать браузер автоматически во время входа
  --allow-root               Разрешить установку в root-аккаунт (не рекомендуется)
  --install-root <path>      Путь для venv. По умолчанию: ~/.local/share/cloudbridge/app
  --app-home <path>          Корневая папка состояния приложения. По умолчанию: ~/.local/share/cloudbridge
  --wrapper-path <path>      Путь к wrapper-скрипту. По умолчанию: ~/.local/bin/cloudbridge-local
  --help                     Показать эту справку
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
    --no-browser)
      NO_BROWSER=1
      shift
      ;;
    --allow-root)
      ALLOW_ROOT=1
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
  echo "Нужен установленный python3." >&2
  exit 1
fi

if [[ "$(id -u)" -eq 0 && "$ALLOW_ROOT" -ne 1 ]]; then
  cat >&2 <<'EOF'
install-linux.sh рассчитан на установку для обычного пользователя и не должен запускаться от root.

Почему это важно:
- интеграция с файловым менеджером установится в /root, а не в вашу обычную сессию
- служба systemd --user будет создана для root
- GUI и пункты в контекстном меню не появятся у обычного пользователя

Запустите installer от своего desktop-пользователя либо передайте --allow-root, только если вам действительно нужна отдельная root-установка.
EOF
  exit 1
fi

if ! python3 - <<'PY' >/dev/null 2>&1
import sqlite3
PY
then
  cat >&2 <<'EOF'
В python3 отсутствует стандартный модуль sqlite3.

CloudBridge использует SQLite для локальной базы состояния, поэтому без sqlite3 приложение не запустится.

На ALT Linux сначала установите пакет с этим модулем, например:
  apt-get install python3-modules-sqlite3
EOF
  exit 1
fi

if [[ "$PROVIDER" == "yandex" && -z "$TOKEN" && ( -z "$YANDEX_CLIENT_ID" || -z "$YANDEX_CLIENT_SECRET" ) ]]; then
  echo "Для provider=yandex нужен либо --token, либо одновременно --yandex-client-id и --yandex-client-secret." >&2
  exit 1
fi

if [[ "$PROVIDER" == "nextcloud" && -z "$NEXTCLOUD_URL" ]]; then
  echo "Для provider=nextcloud нужно указать --nextcloud-url." >&2
  exit 1
fi

if [[ "$PROVIDER" == "nextcloud" && ( ( -n "$NEXTCLOUD_USERNAME" && -z "$NEXTCLOUD_PASSWORD" ) || ( -z "$NEXTCLOUD_USERNAME" && -n "$NEXTCLOUD_PASSWORD" ) ) ]]; then
  echo "--nextcloud-username и --nextcloud-password нужно передавать вместе." >&2
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
  YANDEX_SETUP_ARGS=(setup-yandex --client-id "$YANDEX_CLIENT_ID" --client-secret "$YANDEX_CLIENT_SECRET")
  if [[ "$NO_BROWSER" -eq 1 ]]; then
    YANDEX_SETUP_ARGS+=(--no-browser)
  fi
  if ! "$WRAPPER_PATH" "${YANDEX_SETUP_ARGS[@]}"; then
    cat >&2 <<'EOF'
Не удалось завершить вход в Яндекс.

Проверьте:
- Client ID и Client secret взяты из одного и того же OAuth-приложения
- secret не был перевыпущен после того, как вы его скопировали
- при проблемах с браузером в виртуальной машине попробуйте повторить установку с флагом --no-browser
EOF
    exit 1
  fi
fi

if [[ "$PROVIDER" == "nextcloud" && -n "$NEXTCLOUD_URL" && ( -z "$NEXTCLOUD_USERNAME" || -z "$NEXTCLOUD_PASSWORD" ) ]]; then
  NEXTCLOUD_SETUP_ARGS=(setup-nextcloud --server "$NEXTCLOUD_URL")
  if [[ "$NO_BROWSER" -eq 1 ]]; then
    NEXTCLOUD_SETUP_ARGS+=(--no-browser)
  fi
  if ! "$WRAPPER_PATH" "${NEXTCLOUD_SETUP_ARGS[@]}"; then
    cat >&2 <<'EOF'
Не удалось завершить вход в Nextcloud.

Проверьте:
- адрес сервера указан полностью, включая https://
- браузер смог открыть страницу входа
- если в виртуальной машине есть проблемы с браузером, повторите установку с флагом --no-browser
EOF
    exit 1
  fi
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

Убедитесь, что ~/.local/bin добавлен в PATH.
EOF
