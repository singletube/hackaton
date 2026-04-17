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
