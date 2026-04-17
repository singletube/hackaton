#!/bin/sh
set -e

echo "=== Скрипт настройки CloudBridge для ALT Linux ==="

# Проверка на root
if [ "$(id -u)" -ne 0 ]; then
    echo "ОШИБКА: Этот скрипт необходимо запускать от имени суперпользователя (root)."
    echo "Используйте 'su -' для перехода в root, затем запустите скрипт."
    exit 1
fi

# 1. Обновление репозиториев и установка зависимостей
echo "[1/4] Установка системных зависимостей (APT-RPM)..."
apt-get update

# Пакеты в ALT Linux имеют суффикс -devel вместо -dev
# Устанавливаем python, pip, venv, gcc (для сборки), fuse3, glib2, cairo
apt-get install -y \
    python3 \
    python3-module-pip \
    python3-module-venv \
    python3-devel \
    gcc \
    libfuse3-devel \
    fuse3 \
    pkg-config \
    glib2-devel \
    libcairo-devel \
    libcairo-gobject-devel

# 2. Настройка FUSE
echo "[2/4] Настройка прав доступа FUSE..."
modprobe fuse || echo "Модуль FUSE уже загружен"

# Разрешаем обычным пользователям монтировать FUSE с флагом allow_other
if grep -q "^#user_allow_other" /etc/fuse.conf; then
    sed -i 's/^#user_allow_other/user_allow_other/' /etc/fuse.conf
elif ! grep -q "^user_allow_other" /etc/fuse.conf; then
    echo "user_allow_other" >> /etc/fuse.conf
fi

echo "Системные зависимости установлены."
echo "Теперь вы можете вернуться к обычному пользователю (нажмите Ctrl+D или введите exit)"
echo "и продолжить настройку Python окружения."
