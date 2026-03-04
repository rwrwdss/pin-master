"""
Менеджер кэширования данных о пинах и досках пользователя.
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timedelta


def _cache_dir() -> Path:
    from pinmaster.utils.paths import is_frozen, get_base_dir, get_app_data_dir
    if is_frozen():
        return get_app_data_dir() / "cache"
    return get_base_dir() / "cache"


class CacheManager:
    """Управление кэшем данных Pinterest"""
    
    CACHE_EXPIRY_DAYS = 7
    
    @staticmethod
    def _ensure_cache_dir():
        d = _cache_dir()
        d.mkdir(parents=True, exist_ok=True)
    
    @staticmethod
    def _get_cache_file(username: str, cache_type: str) -> str:
        """
        Возвращает путь к файлу кэша.
        
        Args:
            username: Имя пользователя
            cache_type: Тип кэша ('pins' или 'boards')
        """
        CacheManager._ensure_cache_dir()
        return str(_cache_dir() / f"{username}_{cache_type}.json")
    
    @staticmethod
    def _is_cache_valid(cache_data: Dict) -> bool:
        """
        Проверяет, действителен ли кэш.
        
        Args:
            cache_data: Данные кэша с полем 'timestamp'
        """
        if 'timestamp' not in cache_data:
            return False
        
        try:
            cache_time = datetime.fromisoformat(cache_data['timestamp'])
            expiry_time = cache_time + timedelta(days=CacheManager.CACHE_EXPIRY_DAYS)
            return datetime.now() < expiry_time
        except:
            return False
    
    @staticmethod
    def save_pins(username: str, pins: List[Dict]) -> bool:
        """
        Сохраняет пины пользователя в кэш.
        
        Args:
            username: Имя пользователя
            pins: Список пинов
        """
        try:
            cache_file = CacheManager._get_cache_file(username, 'pins')
            cache_data = {
                'username': username,
                'timestamp': datetime.now().isoformat(),
                'pins': pins,
                'count': len(pins)
            }
            
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)
            
            print(f"✓ Кэш пинов сохранен: {len(pins)} пинов для {username}")
            return True
        except Exception as e:
            print(f"⚠ Ошибка при сохранении кэша пинов: {e}")
            return False
    
    @staticmethod
    def load_pins(username: str) -> Optional[List[Dict]]:
        """
        Загружает пины пользователя из кэша.
        
        Args:
            username: Имя пользователя
            
        Returns:
            Список пинов или None если кэш недействителен или не существует
        """
        try:
            cache_file = CacheManager._get_cache_file(username, 'pins')
            
            if not os.path.exists(cache_file):
                return None
            
            with open(cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            # Проверяем валидность кэша
            if not CacheManager._is_cache_valid(cache_data):
                print(f"⚠ Кэш пинов для {username} устарел, требуется обновление")
                return None
            
            if cache_data.get('username') != username:
                return None
            
            pins = cache_data.get('pins', [])
            print(f"✓ Кэш пинов загружен: {len(pins)} пинов для {username}")
            return pins
            
        except Exception as e:
            print(f"⚠ Ошибка при загрузке кэша пинов: {e}")
            return None
    
    @staticmethod
    def save_boards(username: str, boards: List[Dict]) -> bool:
        """
        Сохраняет доски пользователя в кэш.
        
        Args:
            username: Имя пользователя
            boards: Список досок
        """
        try:
            cache_file = CacheManager._get_cache_file(username, 'boards')
            cache_data = {
                'username': username,
                'timestamp': datetime.now().isoformat(),
                'boards': boards,
                'count': len(boards)
            }
            
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)
            
            print(f"✓ Кэш досок сохранен: {len(boards)} досок для {username}")
            return True
        except Exception as e:
            print(f"⚠ Ошибка при сохранении кэша досок: {e}")
            return False
    
    @staticmethod
    def load_boards(username: str) -> Optional[List[Dict]]:
        """
        Загружает доски пользователя из кэша.
        
        Args:
            username: Имя пользователя
            
        Returns:
            Список досок или None если кэш недействителен или не существует
        """
        try:
            cache_file = CacheManager._get_cache_file(username, 'boards')
            
            if not os.path.exists(cache_file):
                return None
            
            with open(cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            # Проверяем валидность кэша
            if not CacheManager._is_cache_valid(cache_data):
                print(f"⚠ Кэш досок для {username} устарел, требуется обновление")
                return None
            
            if cache_data.get('username') != username:
                return None
            
            boards = cache_data.get('boards', [])
            print(f"✓ Кэш досок загружен: {len(boards)} досок для {username}")
            return boards
            
        except Exception as e:
            print(f"⚠ Ошибка при загрузке кэша досок: {e}")
            return None
    
    @staticmethod
    def clear_cache(username: str = None):
        """
        Очищает кэш для пользователя или весь кэш.
        
        Args:
            username: Имя пользователя (если None, очищает весь кэш)
        """
        try:
            CacheManager._ensure_cache_dir()
            
            if username:
                # Очищаем кэш конкретного пользователя
                pins_file = CacheManager._get_cache_file(username, 'pins')
                boards_file = CacheManager._get_cache_file(username, 'boards')
                
                for cache_file in [pins_file, boards_file]:
                    if os.path.exists(cache_file):
                        os.remove(cache_file)
                        print(f"✓ Кэш удален: {cache_file}")
            else:
                d = _cache_dir()
                for f in d.glob("*.json"):
                    f.unlink()
                    print(f"✓ Кэш удален: {f}")
        except Exception as e:
            print(f"⚠ Ошибка при очистке кэша: {e}")
