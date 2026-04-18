#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

FORMAT="deb"
OUTPUT_DIR="$REPO_ROOT/.dist/packages"
BUILD_ROOT="$REPO_ROOT/.dist/build"
PACKAGE_NAME="cloudbridge"
INSTALL_PREFIX="/opt/cloudbridge"
BIN_LINK="/usr/bin/cloudbridge"

usage() {
  cat <<'EOF'
Usage: build-linux-package.sh [options]

Options:
  --format <deb|rpm>        Package format. Default: deb
  --output-dir <path>       Output directory. Default: .dist/packages
  --build-root <path>       Temporary build root. Default: .dist/build
  --install-prefix <path>   Install prefix inside package. Default: /opt/cloudbridge
  --bin-link <path>         Public wrapper path inside package. Default: /usr/bin/cloudbridge
  --help                    Show this help

Requirements:
  - Linux
  - python3
  - fpm
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --format)
      FORMAT="$2"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --build-root)
      BUILD_ROOT="$2"
      shift 2
      ;;
    --install-prefix)
      INSTALL_PREFIX="$2"
      shift 2
      ;;
    --bin-link)
      BIN_LINK="$2"
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

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This script must run on Linux." >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required" >&2
  exit 1
fi

if ! command -v fpm >/dev/null 2>&1; then
  echo "fpm is required to build .deb/.rpm packages" >&2
  exit 1
fi

case "$FORMAT" in
  deb|rpm)
    ;;
  *)
    echo "Unsupported format: $FORMAT" >&2
    exit 1
    ;;
esac

VERSION="$(
  python3 - <<'PY'
from pathlib import Path
import re

content = Path("pyproject.toml").read_text(encoding="utf-8")
match = re.search(r'^version = "([^"]+)"$', content, re.MULTILINE)
if not match:
    raise SystemExit("Could not read version from pyproject.toml")
print(match.group(1))
PY
)"

STAGE_DIR="$BUILD_ROOT/stage"
VENV_DIR="$STAGE_DIR$INSTALL_PREFIX/venv"
WRAPPER_PATH="$STAGE_DIR$BIN_LINK"
DOC_DIR="$STAGE_DIR/usr/share/doc/$PACKAGE_NAME"

rm -rf "$BUILD_ROOT"
mkdir -p "$VENV_DIR" "$(dirname "$WRAPPER_PATH")" "$DOC_DIR" "$OUTPUT_DIR"

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install "$REPO_ROOT"

cat >"$WRAPPER_PATH" <<EOF
#!/usr/bin/env bash
set -euo pipefail
exec $INSTALL_PREFIX/venv/bin/cloudbridge "\$@"
EOF
chmod +x "$WRAPPER_PATH"

install -m 0644 "$REPO_ROOT/docs/install_linux.md" "$DOC_DIR/install_linux.md"
install -m 0644 "$REPO_ROOT/docs/package_linux.md" "$DOC_DIR/package_linux.md"

fpm \
  -s dir \
  -t "$FORMAT" \
  -n "$PACKAGE_NAME" \
  -v "$VERSION" \
  --prefix / \
  --package "$OUTPUT_DIR" \
  --description "Hybrid cloud file management runtime for Linux" \
  --url "https://example.invalid/cloudbridge" \
  --license "Proprietary" \
  --maintainer "CloudBridge" \
  -C "$STAGE_DIR" \
  .

echo "built=true"
echo "format=$FORMAT"
echo "output_dir=$OUTPUT_DIR"
