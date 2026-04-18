# Установка CloudBridge на ALT Linux с нуля

Ниже описан путь для чистой пользовательской установки из исходников, без сборки собственного RPM.

## 1. Установить системные пакеты

Обновите индекс пакетов и поставьте базовые зависимости:

```bash
su -
apt-get update
apt-get install git python3 python3-module-pip python3-modules-sqlite3 python3-modules-tkinter notify-send
```

Если у вас рабочий стол MATE и вы хотите интеграцию с Caja и эмблемы статусов:

```bash
apt-get install python3-module-caja
```

Если `sudo` настроен в системе, те же команды можно выполнять через `sudo`.

Важно: сам `scripts/install-linux.sh` нужно запускать не от `root`, а от вашего обычного desktop-пользователя.
CloudBridge ставит:

- `~/.local/bin/cloudbridge-local`
- пользовательские file-manager actions
- `systemd --user` service

Если запустить installer от `root`, все это окажется в `/root/.local/...` и не будет работать в вашей обычной сессии.

## 2. Склонировать проект

```bash
cd "$HOME"
git clone <URL_ВАШЕГО_РЕПОЗИТОРИЯ> cloudbridge
cd cloudbridge
```

## 3. Выполнить локальную установку

### Вариант для Yandex

Если у вас уже есть OAuth access token:

```bash
chmod +x scripts/install-linux.sh
./scripts/install-linux.sh \
  --provider yandex \
  --token 'YANDEX_ACCESS_TOKEN' \
  --sync-root "$HOME/CloudBridge" \
  --manager auto
```

Если у вас есть `Client ID` и `Client secret`, можно пройти логин без ручного копирования токена:

```bash
chmod +x scripts/install-linux.sh
./scripts/install-linux.sh \
  --provider yandex \
  --yandex-client-id "YANDEX_CLIENT_ID" \
  --yandex-client-secret "YANDEX_CLIENT_SECRET" \
  --sync-root "$HOME/CloudBridge" \
  --manager auto
```

Важно: при таком входе Яндекс открывает страницу `ya.ru/device`, где нужно ввести код устройства.
Этот код не приходит письмом или SMS. Его печатает сам CloudBridge в терминал как `user_code=...`,
а в графическом окне CloudBridge он показывается в правой панели авторизации и печатается в stdout
как `auth_code=...`.

### Вариант для Nextcloud

```bash
chmod +x scripts/install-linux.sh
./scripts/install-linux.sh \
  --provider nextcloud \
  --nextcloud-url "https://cloud.example.com" \
  --sync-root "$HOME/CloudBridge" \
  --manager auto
```

## 4. Проверить, что wrapper доступен

После установки основной пользовательский запускатель находится здесь:

```text
~/.local/bin/cloudbridge-local
```

Если `~/.local/bin` еще не в `PATH`, запускайте так:

```bash
~/.local/bin/cloudbridge-local discover
```

## 5. Запустить графическую настройку

Первый GUI-слой уже есть, и на ALT Linux его можно использовать как точку входа вместо ручного редактирования конфига:

```bash
~/.local/bin/cloudbridge-local gui
```

Что можно сделать из окна:

- выбрать провайдера
- сменить `sync root`
- настроить `import root` и layout
- пройти `Yandex device flow`
- пройти `Nextcloud browser login`
- запустить `desktop setup`

## 6. Проверить сервис и интеграцию

Если вы не использовали `--skip-service`, installer попытается установить и включить `systemd --user` сервис:

```bash
systemctl --user status cloudbridge.service
```

Если нужно включить вручную:

```bash
systemctl --user daemon-reload
systemctl --user enable --now cloudbridge.service
```

## 7. Базовая проверка после установки

```bash
~/.local/bin/cloudbridge-local discover
~/.local/bin/cloudbridge-local ls /
~/.local/bin/cloudbridge-local gui
```

Для публикации файла по ссылке:

```bash
~/.local/bin/cloudbridge-local share /path/in/cloud --copy
```

## Что ставится локально

- приложение: `~/.local/share/cloudbridge/app`
- runtime-конфиг: `~/.local/share/cloudbridge/config.json`
- sync root: по умолчанию `~/CloudBridge`
- wrapper: `~/.local/bin/cloudbridge-local`

## Что еще важно для ALT Linux

- для GUI нужен пакет `python3-modules-tkinter`
- для уведомлений нужен `notify-send`
- для MATE/Caja интеграции нужен `python3-module-caja`
- если у вас другой файловый менеджер, используйте `--manager nautilus|thunar|nemo|caja`
