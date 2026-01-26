# Инструкции по сборке PinMaster

## Подготовка к сборке

### 1. Установка зависимостей

```bash
pip install -r requirements.txt
pip install pyinstaller
```

### 2. Создание иконки (опционально)

Для macOS создайте файл `icon.icns`:
- Используйте инструмент `iconutil` или онлайн-конвертеры
- Или создайте PNG иконку 512x512 и конвертируйте в ICNS

## Сборка для macOS

### Автоматическая сборка

```bash
./build_macos.sh
```

Скрипт автоматически:
- Очистит предыдущие сборки
- Соберет приложение через PyInstaller
- Создаст .app bundle
- Опционально создаст DMG образ

### Ручная сборка

```bash
pyinstaller pinmaster.spec
```

Результат будет в папке `dist/PinMaster.app`

### Стили (QSS) в продакшене

- `styles.qss` включается в сборку (datas) и лежит в `Contents/Resources/`.
- Приложение ищет файл в `_MEIPASS`, `MacOS`, затем `Resources`; при неудаче использует встроенные стили из `embedded_styles.py`.
- Темная тема с салатовым акцентом применяется в любом случае.

## Структура файлов в продакшене

После сборки приложение использует следующие пути:

### macOS
- **Конфигурация**: `~/Library/Application Support/PinMaster/config.json`
- **Cookies**: `~/Library/Application Support/PinMaster/pinterest_cookies.json`
- **Изображения**: `~/Documents/PinMaster/images/`
- **CSV файлы**: `~/Documents/PinMaster/csv/`
- **Логи**: `~/Library/Application Support/PinMaster/logs/`

### Windows
- **Конфигурация**: `%APPDATA%/PinMaster/config.json`
- **Cookies**: `%APPDATA%/PinMaster/pinterest_cookies.json`
- **Изображения**: `%USERPROFILE%/Documents/PinMaster/images/`
- **CSV файлы**: `%USERPROFILE%/Documents/PinMaster/csv/`

### Linux
- **Конфигурация**: `~/.config/PinMaster/config.json`
- **Cookies**: `~/.config/PinMaster/pinterest_cookies.json`
- **Изображения**: `~/Documents/PinMaster/images/`
- **CSV файлы**: `~/Documents/PinMaster/csv/`

## Docker

### Сборка образа

```bash
docker build -t pinmaster:latest .
```

### Запуск контейнера

```bash
docker-compose up -d
```

Или вручную:

```bash
docker run -d \
  -v $(pwd)/data/config:/app/data/config \
  -v $(pwd)/data/cookies:/app/data/cookies \
  -v $(pwd)/data/images:/app/data/images \
  -v $(pwd)/data/csv:/app/data/csv \
  --name pinmaster \
  pinmaster:latest
```

**Примечание**: GUI приложение в Docker требует Xvfb для headless режима.

## Системный трей

Приложение автоматически добавляется в системный трей при запуске:
- Двойной клик по иконке - показать/скрыть окно
- Правый клик - меню с опциями
- Закрытие окна - приложение остается в трее

## Миграция данных

При первом запуске продакшен версии приложение автоматически мигрирует:
- `config.json` из директории разработки
- `pinterest_cookies.json` из директории разработки
- Папки `pinterest_images_*` из директории разработки

## Устранение проблем

### Приложение не запускается

1. Проверьте логи в `~/Library/Application Support/PinMaster/logs/`
2. Убедитесь, что все зависимости установлены
3. Проверьте права доступа к файлам

### ChromeDriver не найден

Приложение использует `webdriver-manager` для автоматической загрузки ChromeDriver.
Если возникают проблемы:
1. Убедитесь, что Chrome установлен
2. Проверьте интернет-соединение
3. Проверьте права доступа к директории временных файлов

### Проблемы с путями

Если файлы не находятся:
1. Проверьте, что директории созданы автоматически
2. Проверьте права доступа
3. Посмотрите логи приложения
