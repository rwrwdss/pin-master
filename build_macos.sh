#!/bin/bash
# Скрипт для сборки PinMaster для macOS

set -e

APP_NAME="PinMaster"
BUILD_DIR="build"
DIST_DIR="dist"

echo "🔨 Начинаем сборку $APP_NAME для macOS..."

# Создаем директории
mkdir -p $BUILD_DIR
mkdir -p $DIST_DIR

# Проверяем наличие PyInstaller
if ! command -v pyinstaller &> /dev/null; then
    echo "❌ PyInstaller не установлен. Устанавливаем..."
    pip install pyinstaller
fi

# Очищаем предыдущие сборки (не удаляем pinmaster.spec)
echo "🧹 Очищаем предыдущие сборки..."
rm -rf $BUILD_DIR/*
rm -rf $DIST_DIR/*

# Собираем приложение (используем spec файл)
echo "📦 Собираем приложение..."
if [ -f "icon.icns" ]; then
    pyinstaller --clean pinmaster.spec
else
    echo "  (иконка icon.icns не найдена, собираем без неё)"
    pyinstaller --clean pinmaster.spec
fi

# Проверяем результат
if [ -d "$DIST_DIR/$APP_NAME.app" ]; then
    echo "✅ Сборка завершена успешно!"
    echo "📁 Результат находится в: $DIST_DIR/"
    
    # Создаем DMG если передан аргумент --dmg
    if [[ "$1" == "--dmg" ]]; then
        echo "📦 Создаем DMG образ..."
        hdiutil create -volname "$APP_NAME" -srcfolder "$DIST_DIR/$APP_NAME.app" -ov -format UDZO "$DIST_DIR/${APP_NAME}.dmg"
        echo "✅ DMG образ создан: $DIST_DIR/${APP_NAME}.dmg"
    else
        echo "  (для DMG установщика запустите: $0 --dmg)"
    fi
    echo ""
    echo "Приложение: $DIST_DIR/$APP_NAME.app"
    echo "Системный трей: PinMaster"
else
    echo "❌ Ошибка сборки!"
    exit 1
fi

echo "🎉 Готово!"
