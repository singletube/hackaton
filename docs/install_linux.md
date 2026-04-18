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

## Yandex Install Without Manual Token Copy

If you have a Yandex OAuth app `Client ID` and `Client secret`, CloudBridge can complete login
through the device-code flow and store the resulting token automatically:

```bash
chmod +x scripts/install-linux.sh
./scripts/install-linux.sh \
  --provider yandex \
  --yandex-client-id "YANDEX_CLIENT_ID" \
  --yandex-client-secret "YANDEX_CLIENT_SECRET" \
  --sync-root "$HOME/CloudBridge" \
  --manager auto
```

The installer runs `cloudbridge setup-yandex`, opens the verification page when possible, and stores
the resulting token in:

```text
~/.local/share/cloudbridge/config.json
```

If the browser does not open automatically, run the setup manually:

```bash
cloudbridge-local setup-yandex \
  --client-id "YANDEX_CLIENT_ID" \
  --client-secret "YANDEX_CLIENT_SECRET"
```

## Nextcloud Install

For Nextcloud, the easiest path is browser-based login with an app password:

```bash
chmod +x scripts/install-linux.sh
./scripts/install-linux.sh \
  --provider nextcloud \
  --nextcloud-url "https://cloud.example.com" \
  --sync-root "$HOME/CloudBridge" \
  --manager auto
```

The installer writes the local wrapper, starts `cloudbridge setup-nextcloud --server ...`,
opens the Nextcloud login flow, and stores the resulting app password in:

```text
~/.local/share/cloudbridge/config.json
```

If your browser does not open automatically, run the setup manually after install:

```bash
cloudbridge-local setup-nextcloud --server "https://cloud.example.com"
```

## Options

- `--manager auto|nautilus|thunar|nemo|caja`
- `--import-layout flat|by-parent|by-date`
- `--service-name <name>`
- `--skip-service`
- `--provider yandex|nextcloud`
- `--token <yandex-access-token>`
- `--yandex-client-id <id>`
- `--yandex-client-secret <secret>`
- `--nextcloud-url <url>`
- `--nextcloud-username <name>`
- `--nextcloud-password <app-password>`
- `--sync-root <path>`
- `--import-root <cloud-path>`
- `--install-root <path>`
- `--wrapper-path <path>`

## After Install

The wrapper can be used directly:

```bash
cloudbridge-local discover
cloudbridge-local daemon --poll-interval 2 --refresh-interval 30
cloudbridge-local share /path/in/cloud --copy
cloudbridge-local desktop-setup --manager auto
```

If `~/.local/bin` is not in `PATH`, run it by full path:

```bash
~/.local/bin/cloudbridge-local discover
```

Saved runtime config lives in:

```text
~/.local/share/cloudbridge/config.json
```

Environment variables still override the saved config if you need one-off changes.

For manual setup after install:

```bash
cloudbridge-local setup-yandex --client-id "YANDEX_CLIENT_ID" --client-secret "YANDEX_CLIENT_SECRET"
cloudbridge-local setup-nextcloud --server "https://cloud.example.com"
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

For Nextcloud, the same flag works:

```bash
./scripts/install-linux.sh --provider nextcloud --nextcloud-url "https://cloud.example.com" --skip-service
```

## External File Upload

Right-click upload actions send files to `CLOUDBRIDGE_IMPORT_ROOT`.
Right-click share actions create or reuse a public link for files inside the sync root and copy it to the clipboard.
For local files outside the sync root, the share action uploads the file first and then copies the public link.

On Nautilus, CloudBridge also adds status emblems for files inside the sync root:

- `placeholder`
- `queued / syncing`
- `error`
- `local_only`
- `publicly shared`

- `flat`: `/incoming/photo.jpg`
- `by-parent`: `/incoming/Pictures/photo.jpg`
- `by-date`: `/incoming/2026/04/photo.jpg`

If a target name already exists, CloudBridge creates a safe deduplicated name like `photo (2).jpg`.

## System Packages

If you want a `.deb` or `.rpm` package instead of the per-user local install flow, use
[package_linux.md](./package_linux.md).
