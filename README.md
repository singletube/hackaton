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
- спросит, где отслеживать переносы из sync-папки: только `home` или расширенно `all`;
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

При запуске CloudBridge проверяет локальную папку и загружает в Яндекс.Диск файлы, которых еще нет в облаке. После успешной загрузки такие файлы заменяются локальными 0-байтными заглушками. Файлы из `ignore-list` не загружаются.

Если нужно временно отключить стартовую загрузку локальных файлов:

```bash
export BOOTSTRAP_LOCAL=0
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
3. дождется закрытия приложения;
4. если файл изменился, загрузит его обратно в Яндекс.Диск;
5. удалит временную копию после успешной синхронизации.

Временные сессии хранятся здесь:

```text
~/.cache/cloudbridge/sessions/
```

Если при загрузке обратно произошла ошибка, session-папка не удаляется, чтобы изменения не потерялись.

### Сохранить файл локально вместо заглушки

Если нужно скачать файл на компьютер и больше не отправлять его обратно в Яндекс.Диск, нажми по заглушке правой кнопкой в Thunar и выбери:

```text
Store Locally
```

CloudBridge:

1. скачает настоящий файл поверх заглушки в той же папке;
2. добавит путь в локальный ignore-list;
3. не будет удалять копию из Яндекс.Диска;
4. watcher перестанет загружать этот файл обратно и больше не будет превращать его в заглушку.

Ignore-list хранится здесь:

```text
~/.config/cloudbridge/ignored.json
```

### Перенести файл из sync-папки наружу

Если перетащить файл-заглушку из синхронизируемой папки в обычную папку, CloudBridge распознает вынос из sync-папки, заменит созданную снаружи 0-байтную заглушку настоящим файлом из Яндекс.Диска и после успешного скачивания удалит исходный файл из Яндекс.Диска.

Для обычного удаления внутри sync-папки CloudBridge ждет короткое окно, чтобы отличить удаление от переноса наружу. Длительность можно поменять переменной:

```bash
export CLOUDBRIDGE_OUTBOUND_MOVE_WINDOW=10
```

Во время установки можно выбрать, где watcher будет дополнительно слушать переносы из sync-папки:

```text
home: /home/kali
all:  /home/kali, /tmp, /media, /mnt
```

Режим `all` покрывает домашнюю папку, временные папки, подключенные носители и VirtualBox shared folders. Это не буквальное `/`, чтобы не слушать системные зоны вроде `/proc`, `/sys`, `/dev`.

Если нужно поменять это вручную, укажи папки через `:` в `~/.config/cloudbridge/env`:

```bash
export CLOUDBRIDGE_OUTBOUND_WATCHES="/home/kali:/tmp:/media/sf_hackaton"
```

После изменения конфига перезапусти `cloudbridge-start`.

Если перенести настоящий файл обратно из обычной папки в sync-папку, CloudBridge загрузит его в Яндекс.Диск и снова заменит локальную копию 0-байтной заглушкой.

### Вернуть локальный файл обратно в облачный режим

Если файл был сохранён локально через `Store Locally`, его можно вернуть в облачный режим. Нажми по локальному файлу правой кнопкой в Thunar и выбери:

```text
Restore to Cloud
```

CloudBridge:

1. загрузит текущий локальный файл в Яндекс.Диск;
2. заменит локальный файл на 0-байтную заглушку;
3. удалит путь из ignore-list;
4. watcher снова будет считать файл облачным.

Если загрузка в Яндекс.Диск завершилась ошибкой, файл останется локальным и сохранится в ignore-list.

### Создание ссылок

В Thunar нажми правой кнопкой по файлу и выбери действие в подменю:

```text
CloudBridge
```

Доступные действия:

- `Create Read-only Link` — публикует файл в Яндекс.Диске и копирует публичную read-only ссылку в буфер обмена.

Для копирования в буфер используется `xclip`, `xsel` или `wl-copy`, если один из этих инструментов установлен. Последняя созданная ссылка дополнительно сохраняется в:

```text
~/.cache/cloudbridge/last_share_link.txt
```

Логи действий из контекстного меню пишутся сюда:

```text
~/.cache/cloudbridge/actions.log
```

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
