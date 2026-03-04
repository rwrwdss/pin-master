#!/bin/bash
# Быстрое создание DMG установщика из существующего .app

APP_NAME="PinMaster"
BASE_DIR="/Users/bulatmuhametzanov/Desktop/пинтерест"
DIST_DIR="$BASE_DIR/dist"
APP_PATH="$DIST_DIR/${APP_NAME}.app"
DMG_PATH="$DIST_DIR/${APP_NAME}.dmg"

echo "💿 Создание DMG установщика для ${APP_NAME}..."
echo ""

# Проверяем наличие .app
if [ ! -d "$APP_PATH" ]; then
    echo "❌ Приложение не найдено: $APP_PATH"
    echo "   Сначала запустите: python3 build_macos_installer.py"
    exit 1
fi

echo "✓ Найдено приложение: $APP_PATH"

# Удаляем старый DMG если есть
if [ -f "$DMG_PATH" ]; then
    echo "   Удаление старого DMG..."
    rm -f "$DMG_PATH"
fi

# Создаем временную папку
DMG_TEMP="$DIST_DIR/dmg_temp"
if [ -d "$DMG_TEMP" ]; then
    echo "   Очистка временной папки..."
    rm -rf "$DMG_TEMP"
fi

mkdir -p "$DMG_TEMP"
echo "✓ Создана временная папка"

# Копируем .app
echo "   Копирование приложения..."
cp -R "$APP_PATH" "$DMG_TEMP/"

# Создаем симлинк на Applications
echo "   Создание ссылки на Applications..."
ln -s /Applications "$DMG_TEMP/Applications"

# Создаем временный DMG
TEMP_DMG="$DIST_DIR/${APP_NAME}_temp.dmg"
if [ -f "$TEMP_DMG" ]; then
    rm -f "$TEMP_DMG"
fi

echo "   Создание DMG образа..."
hdiutil create -volname "$APP_NAME" -srcfolder "$DMG_TEMP" -ov -format UDRW "$TEMP_DMG"

if [ $? -ne 0 ]; then
    echo "❌ Ошибка при создании DMG"
    rm -rf "$DMG_TEMP"
    exit 1
fi

# Конвертируем в сжатый формат
echo "   Сжатие DMG..."
hdiutil convert "$TEMP_DMG" -format UDZO -o "$DMG_PATH"

# Очистка
rm -f "$TEMP_DMG"
rm -rf "$DMG_TEMP"

if [ -f "$DMG_PATH" ]; then
    SIZE=$(du -h "$DMG_PATH" | cut -f1)
    echo ""
    echo "✅ DMG установщик создан!"
    echo "   Путь: $DMG_PATH"
    echo "   Размер: $SIZE"
    echo ""
    echo "💡 Для тестирования:"
    echo "   open \"$DMG_PATH\""
else
    echo "❌ DMG файл не создан"
    exit 1
fi

