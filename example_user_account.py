"""
Пример использования функций для работы с аккаунтом пользователя Pinterest.
"""

from pinterest_selenium_parser import PinterestSeleniumParser
from pinterest_parser import PinterestParser
import json

def example_get_account_info():
    """Пример получения информации об аккаунте"""
    print("=" * 80)
    print("ПРИМЕР: Получение информации об аккаунте")
    print("=" * 80)
    
    parser = PinterestSeleniumParser(
        headless=False,  # Показываем браузер для отладки
        download_images=False,
        auto_login=True
    )
    
    try:
        # Получаем информацию об аккаунте
        account_info = parser.get_account_info()
        
        if account_info:
            print("\n✓ Информация об аккаунте получена:")
            print(json.dumps(account_info, indent=2, ensure_ascii=False))
            
            username = account_info['username']
            
            # Парсим пины пользователя
            print("\n" + "=" * 80)
            print("ПРИМЕР: Парсинг пинов пользователя")
            print("=" * 80)
            
            pins = parser.parse_user_pins(username=username, max_pins=5)
            
            if pins:
                print(f"\n✓ Найдено {len(pins)} пинов")
                for i, pin in enumerate(pins, 1):
                    print(f"\n{i}. {pin.get('title', 'Без названия')}")
                    print(f"   Ссылка: {pin.get('pin_link', '')}")
                    print(f"   Автор: {pin.get('author', '')}")
            else:
                print("⚠ Пины не найдены")
            
            # Парсим доски пользователя
            print("\n" + "=" * 80)
            print("ПРИМЕР: Парсинг досок пользователя")
            print("=" * 80)
            
            boards = parser.parse_user_boards(username=username)
            
            if boards:
                print(f"\n✓ Найдено {len(boards)} досок")
                for i, board in enumerate(boards, 1):
                    print(f"\n{i}. {board.get('board_name', 'Без названия')}")
                    print(f"   URL: {board.get('board_url', '')}")
                    if board.get('pins_count'):
                        print(f"   Пинов: {board.get('pins_count')}")
                    
                    # Можно парсить пины из конкретной доски
                    if i == 1:  # Пример для первой доски
                        print("\n" + "-" * 80)
                        print(f"ПРИМЕР: Парсинг пинов из доски '{board.get('board_name')}'")
                        print("-" * 80)
                        
                        board_pins = parser.parse_board_pins(
                            username=username,
                            board_name=board.get('board_name'),
                            max_pins=3
                        )
                        
                        if board_pins:
                            print(f"✓ Найдено {len(board_pins)} пинов в доске")
                            for j, pin in enumerate(board_pins, 1):
                                print(f"  {j}. {pin.get('title', 'Без названия')[:50]}")
            else:
                print("⚠ Доски не найдены")
        else:
            print("⚠ Не удалось получить информацию об аккаунте")
    
    finally:
        parser.close()


if __name__ == "__main__":
    example_get_account_info()
