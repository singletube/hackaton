# CloudBridge Linux Packaging

## Build `.deb` or `.rpm`

Run on Linux:

```bash
chmod +x scripts/build-linux-package.sh
./scripts/build-linux-package.sh --format deb
./scripts/build-linux-package.sh --format rpm
```

The script builds a self-contained package with:

- `cloudbridge` runtime under `/opt/cloudbridge/venv`
- public wrapper at `/usr/bin/cloudbridge`
- install docs under `/usr/share/doc/cloudbridge`

## Requirements

- `python3`
- `fpm`

Example install of `fpm`:

```bash
gem install --no-document fpm
```

## Output

Packages are written to:

```text
.dist/packages
```

## Notes

These packages provide the runtime binary. The recommended post-install step is:

```bash
cloudbridge desktop-setup --manager auto
```

For Nextcloud, complete browser-based login after install:

```bash
cloudbridge setup-nextcloud --server "https://cloud.example.com"
```

For Yandex, you can avoid manual token copy if you have the OAuth app credentials:

```bash
cloudbridge setup-yandex \
  --client-id "YANDEX_CLIENT_ID" \
  --client-secret "YANDEX_CLIENT_SECRET"
```

If you want to skip one of the desktop integration steps:

```bash
cloudbridge desktop-setup --skip-service
cloudbridge desktop-setup --skip-filemanager
```

If you prefer the per-user local install path instead of a system package, use [install_linux.md](./install_linux.md).
