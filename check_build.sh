#!/bin/bash
# Скрипт для проверки статуса сборки (dist — относительно директории скрипта)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_DIR="${SCRIPT_DIR}/dist"

echo "Проверка результатов сборки..."
echo ""

if [ -d "$DIST_DIR" ]; then
    echo "Содержимое папки dist:"
    ls -lh "$DIST_DIR" 2>/dev/null
    
    if [ -f "$DIST_DIR/PinMaster.dmg" ]; then
        echo ""
        echo "✅ DMG установщик найден!"
        echo "   Путь: $DIST_DIR/PinMaster.dmg"
        echo "   Размер: $(du -h "$DIST_DIR/PinMaster.dmg" | cut -f1)"
    fi
    
    if [ -d "$DIST_DIR/PinMaster.app" ]; then
        echo ""
        echo "✅ .app bundle найден!"
        echo "   Путь: $DIST_DIR/PinMaster.app"
        echo "   Размер: $(du -sh "$DIST_DIR/PinMaster.app" | cut -f1)"
    fi
else
    echo "Папка dist не найдена. Сборка еще не завершена или не началась."
fi

echo ""
echo "Процессы сборки:"
ps aux | grep -i "build_macos_installer\|pyinstaller" | grep -v grep | head -3

