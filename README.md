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

---

## CloudBridge: текущий прототип (этап 1)

Реализован базовый каркас:
- Async `StateDB` на SQLite (`aiosqlite`);
- `YandexDiskProvider` с реальными REST-запросами (`aiohttp`);
- `HybridManager` для объединения локального и облачного дерева;
- `LocalWatcher` на `watchdog`;
- FUSE3 read-only слой (`CloudBridgeFS` на `pyfuse3`);
- CLI: `init-db`, `discover`, `watch`, `sync`, `mount`.

### Быстрый старт

1. Установка:
```bash
python -m pip install -e .[dev]
```

2. Настройка:
```bash
cp .env.example .env
# укажите YA_DISK_TOKEN
# для полного снимка дерева (строгое совпадение локально/в облаке):
# CLOUDBRIDGE_DISCOVERY_DEPTH=-1
```

3. Инициализация БД:
```bash
python -m cloudbridge init-db
```

4. Discovery (облако + локальная структура):
```bash
python -m cloudbridge discover
```

5. Запуск watcher:
```bash
python -m cloudbridge watch
```

6. Двунаправленное выравнивание дерева (локально/облако):
```bash
python -m cloudbridge sync
```

7. Монтирование FUSE3:
```bash
mkdir -p ~/CloudBridgeMount
python -m cloudbridge mount --mountpoint ~/CloudBridgeMount
```

### Ubuntu (голая система)

1. Пакеты ОС:
```bash
sudo apt update
sudo apt install -y \
  python3 python3-venv python3-pip \
  fuse3 libfuse3-dev pkg-config build-essential
```

2. Клонирование и окружение:
```bash
git clone <YOUR_REPO_URL> cloudbridge
cd cloudbridge
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .[dev,fuse]
```

3. Настройка:
```bash
cp .env.example .env
# Вставь OAuth токен:
# YA_DISK_TOKEN=...
```

4. Инициализация и discovery:
```bash
python -m cloudbridge init-db
python -m cloudbridge discover
```

5. Монтирование:
```bash
mkdir -p ~/CloudBridgeMount
python -m cloudbridge mount --mountpoint ~/CloudBridgeMount
```

6. (Опционально) доступ другим пользователям:
```bash
echo user_allow_other | sudo tee -a /etc/fuse.conf
python -m cloudbridge mount --mountpoint ~/CloudBridgeMount --allow-other
```

### Тесты
```bash
python -m pytest tests -p no:cacheprovider
```
