# Авторизация в Pinterest

## Настройка

1. Откройте файл `config.json` и установите `enable_login: true`:

```json
{
  "enable_login": true,
  "login_url": "https://ru.pinterest.com/login/",
  "cookies_file": "pinterest_cookies.json",
  "headless": false,
  "wait_for_manual_login": true,
  "login_timeout": 300
}
```

## Использование

### Способ 1: Автоматический логин через парсер

При запуске парсера с `enable_login: true` в конфиге, он автоматически:
1. Проверит наличие валидной сессии
2. Если сессии нет, откроет браузер на странице логина
3. Дождется ручного входа пользователя
4. Сохранит cookies сессии

```bash
python pinterest_selenium_parser.py
```

### Способ 2: Отдельная авторизация

Запустите модуль авторизации отдельно:

```bash
python pinterest_auth.py
```

Или в коде:

```python
from pinterest_auth import PinterestAuth

auth = PinterestAuth(headless=False)
if auth.authenticate():
    print("Авторизация успешна!")
    # Cookies сохранены в pinterest_cookies.json
auth.close()
```

## Как работает авторизация

1. **Проверка существующей сессии**: Система проверяет наличие файла `pinterest_cookies.json` и валидность cookies
2. **Ручной логин**: Если сессии нет, открывается браузер на странице логина Pinterest
3. **Ожидание входа**: Пользователь вручную вводит логин и пароль
4. **Сохранение сессии**: После успешного входа все cookies сохраняются в `pinterest_cookies.json`
5. **Использование сессии**: При следующих запусках используется сохраненная сессия

## Параметры конфига

- `enable_login` (bool): Включить автоматический логин
- `login_url` (str): URL страницы логина
- `cookies_file` (str): Путь к файлу с cookies
- `headless` (bool): Запускать браузер в фоновом режиме (false для логина)
- `wait_for_manual_login` (bool): Ждать ручного входа
- `login_timeout` (int): Таймаут ожидания логина в секундах

## Важные замечания

⚠️ **Безопасность:**
- Файл `pinterest_cookies.json` содержит ваши cookies сессии
- Не передавайте этот файл третьим лицам
- Файл уже в `.gitignore` и не будет закоммичен

⚠️ **Срок действия:**
- Cookies могут истечь через некоторое время
- Если парсер перестал работать, выполните повторную авторизацию

## Анализ авторизации Pinterest

Pinterest использует следующие cookies для авторизации:
- `_auth` - основной токен авторизации
- `_pinterest_sess` - идентификатор сессии
- `csrftoken` - токен защиты от CSRF атак
- `_routing_id` - идентификатор маршрутизации
- `sessionFingerprint` - отпечаток сессии для безопасности

После успешного входа эти cookies устанавливаются браузером и используются для всех последующих запросов.
