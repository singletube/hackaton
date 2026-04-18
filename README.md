GitFlow от dev: обязательный процесс разработки
Работаем по GitFlow с базовой веткой разработки dev.

Обязательные правила для работы с dev
Перед коммитом при работе с dev обязательно сделать pull:
git checkout dev
git pull --rebase origin dev
Для задачи создавать временную рабочую ветку только от dev:
git checkout dev
git pull --rebase origin dev
git checkout -b feature/<short-topic>
После изменений: коммит и push рабочей ветки:
git add -A
git commit -m "Краткое описание изменения"
git push -u origin feature/<short-topic>
PR в dev создается только из рабочей ветки (не прямым push в dev).

Аппрув PR в dev могут делать все разработчики команды.

После merge в dev временная ветка удаляется (локально и на сервере).

## CloudBridge: установка и запуск в Kali

### Быстрый первый запуск

В Kali открой терминал в папке проекта:

```bash
cd /media/sf_hackaton
chmod +x setup_kali.sh
./setup_kali.sh
```

Скрипт сам:

- установит системные зависимости через `apt`;
- создаст виртуальное окружение `.venv`;
- установит Python-зависимости из `requirements.txt`;
- спросит Яндекс OAuth token;
- спросит облачную папку Яндекс.Диска, например `/CloudBridgeTest`;
- спросит локальную папку, которая будет видна в Thunar, например `/home/kali/Videos/copypapka`;
- сохранит конфиг в `~/.config/cloudbridge/env`;
- настроит контекстное меню Thunar `Open with CloudBridge`;
- создаст команды `cloudbridge-start` и `cloudbridge-open`.

Если после установки команда `cloudbridge-start` не находится, добавь локальные бинарники в `PATH`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Чтобы сохранить это навсегда:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

### Запуск демона синхронизации

После настройки запусти CloudBridge:

```bash
cloudbridge-start
```

Этот процесс должен оставаться открытым. Он пишет лог в:

```text
/tmp/cloudbridge-daemon.log
```

Открой локальную папку в Thunar:

```bash
thunar /home/kali/Videos/copypapka
```

### Открытие файлов из облака

В Thunar нажми правой кнопкой по файлу-заглушке и выбери:

```text
Open with CloudBridge
```

CloudBridge:

1. скачает настоящий файл во временную session-папку;
2. откроет файл подходящим приложением;
3. дождется закрытия приложения или нажатия Enter в терминале;
4. если файл изменился, загрузит его обратно в Яндекс.Диск;
5. удалит временную копию после успешной синхронизации.

Временные сессии хранятся здесь:

```text
~/.cache/cloudbridge/sessions/
```

Если при загрузке обратно произошла ошибка, session-папка не удаляется, чтобы изменения не потерялись.

### Ручной запуск открытия файла

Если нужно проверить без контекстного меню Thunar:

```bash
source ~/.config/cloudbridge/env
cd /media/sf_hackaton
"$CLOUDBRIDGE_PYTHON" -m src.cloud_open "/home/kali/Videos/copypapka/docs/123.txt"
```

Также можно указать облачный путь напрямую:

```bash
"$CLOUDBRIDGE_PYTHON" -m src.cloud_open "/CloudBridgeTest/docs/123.txt"
```

### Полезные команды

Переустановить пункт меню Thunar:

```bash
source ~/.config/cloudbridge/env
cd /media/sf_hackaton
"$CLOUDBRIDGE_PYTHON" scratch/install_thunar_action.py \
  --local-path "$LOCAL_PATH" \
  --remote-root "$YANDEX_PATH" \
  --env-file ~/.config/cloudbridge/env \
  --python-bin "$CLOUDBRIDGE_PYTHON"
thunar -q
```

Проверить DNS до Яндекс.Диска:

```bash
getent hosts cloud-api.yandex.net
curl -I https://cloud-api.yandex.net
```
