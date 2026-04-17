# CloudBridge Linux Install

## Quick Install

Run from the project root:

```bash
chmod +x scripts/install-linux.sh
./scripts/install-linux.sh \
  --token 'YANDEX_DISK_TOKEN' \
  --sync-root "$HOME/CloudBridge" \
  --import-root "/incoming" \
  --import-layout by-parent \
  --manager auto
```

This installs CloudBridge into a local virtual environment under `~/.local/share/cloudbridge/app`,
creates a wrapper at `~/.local/bin/cloudbridge-local`, initializes the local database, and installs
file-manager actions for the detected Linux desktop. By default it also installs a
`systemd --user` service and tries to enable it immediately.

## Options

- `--manager auto|nautilus|thunar|nemo|caja`
- `--import-layout flat|by-parent|by-date`
- `--service-name <name>`
- `--skip-service`
- `--sync-root <path>`
- `--import-root <cloud-path>`
- `--install-root <path>`
- `--wrapper-path <path>`

## After Install

The wrapper can be used directly:

```bash
cloudbridge-local discover
cloudbridge-local daemon --poll-interval 2 --refresh-interval 30
```

If `~/.local/bin` is not in `PATH`, run it by full path:

```bash
~/.local/bin/cloudbridge-local discover
```

## Background Service

The installer creates a `systemd --user` unit by default.

Check status:

```bash
systemctl --user status cloudbridge.service
```

Manual reload and enable:

```bash
systemctl --user daemon-reload
systemctl --user enable --now cloudbridge.service
```

If you do not want the background daemon during install:

```bash
./scripts/install-linux.sh --token 'YANDEX_DISK_TOKEN' --skip-service
```

## External File Upload

Right-click upload actions send files to `CLOUDBRIDGE_IMPORT_ROOT`.

- `flat`: `/incoming/photo.jpg`
- `by-parent`: `/incoming/Pictures/photo.jpg`
- `by-date`: `/incoming/2026/04/photo.jpg`

If a target name already exists, CloudBridge creates a safe deduplicated name like `photo (2).jpg`.
