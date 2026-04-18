#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${HOME}/.config/cloudbridge/env"
if [[ ! -f "${ENV_FILE}" ]]; then
  printf '[CloudBridge] missing config: %s\n' "${ENV_FILE}" >&2
  printf '[CloudBridge] run ./setup.sh first\n' >&2
  exit 1
fi

source "${ENV_FILE}"
cd "${CLOUDBRIDGE_PROJECT_DIR}"
exec "${CLOUDBRIDGE_PYTHON}" -m src.main
