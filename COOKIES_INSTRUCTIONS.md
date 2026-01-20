# Инструкция по получению cookies для авторизации в Pinterest

## Способ 1: Через DevTools браузера (Рекомендуется)

1. Откройте Pinterest в браузере (Chrome, Safari, Firefox) и **войдите в свой аккаунт**
2. Откройте DevTools:
   - **Chrome/Safari**: `Cmd + Option + I` (Mac) или `F12` (Windows/Linux)
   - **Firefox**: `Cmd + Option + I` (Mac) или `F12` (Windows/Linux)
3. Перейдите на вкладку:
   - **Chrome**: `Application` → `Storage` → `Cookies` → `https://www.pinterest.com`
   - **Safari**: `Storage` → `Cookies` → `https://www.pinterest.com`
   - **Firefox**: `Storage` → `Cookies` → `https://www.pinterest.com`
4. Скопируйте все cookies в формате:
   ```
   _auth=значение; _pinterest_sess=значение; csrftoken=значение; ...
   ```
5. Запустите утилиту:
   ```bash
   python cookies_manager.py
   ```
6. Выберите опцию `3` и вставьте скопированную строку

## Способ 2: Экспорт через расширение браузера

### Chrome/Safari:
1. Установите расширение "Cookie-Editor" или "EditThisCookie"
2. Откройте Pinterest и войдите
3. Откройте расширение и экспортируйте cookies в JSON
4. Сохраните файл как `pinterest_cookies.json` в папке проекта

### Firefox:
1. Установите расширение "Cookie-Editor"
2. Откройте Pinterest и войдите
3. Экспортируйте cookies в JSON
4. Сохраните файл как `pinterest_cookies.json`

## Способ 3: Ручное создание JSON файла

Создайте файл `pinterest_cookies.json` со следующим содержимым:

```json
{
  "_auth": "ваше_значение",
  "_pinterest_sess": "ваше_значение",
  "csrftoken": "ваше_значение",
  "_routing_id": "ваше_значение",
  "sessionFingerprint": "ваше_значение"
}
```

**Важные cookies для авторизации:**
- `_auth` - основной cookie авторизации
- `_pinterest_sess` - сессия пользователя
- `csrftoken` - токен защиты от CSRF
- `_routing_id` - идентификатор маршрутизации
- `sessionFingerprint` - отпечаток сессии

## Проверка авторизации

После загрузки cookies, парсер автоматически проверит авторизацию.
Вы также можете проверить вручную:

```python
from cookies_manager import CookiesManager, load_cookies_from_file
import requests

cookies = load_cookies_from_file("pinterest_cookies.json")
session = requests.Session()
for name, value in cookies.items():
    session.cookies.set(name, value, domain='.pinterest.com')

is_authorized = CookiesManager.check_authorization(session)
print(f"Авторизован: {is_authorized}")
```

## Важные замечания

⚠️ **Безопасность:**
- НЕ коммитьте файл `pinterest_cookies.json` в git (он уже в .gitignore)
- Cookies имеют срок действия, периодически их нужно обновлять
- Не передавайте файл с cookies третьим лицам

⚠️ **Срок действия:**
- Cookies могут истечь через некоторое время
- Если парсер перестал работать, обновите cookies

## Использование

После создания файла `pinterest_cookies.json`, парсер автоматически будет использовать его:

```python
from pinterest_parser import PinterestParser

# Автоматически загрузит cookies из pinterest_cookies.json
parser = PinterestParser()

# Или укажите свой файл
parser = PinterestParser(cookies_file="my_cookies.json")
```
