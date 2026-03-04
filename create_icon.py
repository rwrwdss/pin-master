#!/usr/bin/env python3
"""
Скрипт для создания иконки приложения PinMaster
Создает PNG изображения разных размеров и конвертирует в .icns
"""

import os
import subprocess
from PIL import Image, ImageDraw, ImageFont

def create_icon_images():
    """Создает PNG изображения разных размеров для иконки"""
    
    # Размеры для macOS иконки
    sizes = [
        (16, 16),
        (32, 32),
        (64, 64),
        (128, 128),
        (256, 256),
        (512, 512),
        (1024, 1024)
    ]
    
    iconset_dir = "icon.iconset"
    os.makedirs(iconset_dir, exist_ok=True)
    
    # Цвета: темный фон, салатовый акцент (как в приложении)
    bg_color = (30, 30, 30)  # Темный фон
    accent_color = (144, 238, 144)  # Салатовый (lightgreen)
    text_color = (255, 255, 255)  # Белый текст
    
    for size in sizes:
        # Создаем изображение
        img = Image.new('RGBA', size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Рисуем фон с закругленными углами
        margin = max(2, size[0] // 16)
        draw.rounded_rectangle(
            [margin, margin, size[0] - margin, size[1] - margin],
            radius=size[0] // 8,
            fill=bg_color
        )
        
        # Рисуем букву "P" для PinMaster
        try:
            # Пробуем использовать системный шрифт
            font_size = int(size[0] * 0.6)
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
            except:
                try:
                    font = ImageFont.truetype("/System/Library/Fonts/Arial.ttf", font_size)
                except:
                    font = ImageFont.load_default()
        except:
            font = ImageFont.load_default()
        
        # Получаем размер текста
        bbox = draw.textbbox((0, 0), "P", font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        # Центрируем текст
        x = (size[0] - text_width) // 2
        y = (size[1] - text_height) // 2 - bbox[1]
        
        # Рисуем букву "P" белым цветом
        draw.text((x, y), "P", fill=text_color, font=font)
        
        # Добавляем салатовую полоску внизу
        stripe_height = max(2, size[1] // 8)
        draw.rectangle(
            [margin, size[1] - margin - stripe_height, size[0] - margin, size[1] - margin],
            fill=accent_color
        )
        
        # Сохраняем в правильном формате для iconutil
        if size == (16, 16):
            filename = "icon_16x16.png"
        elif size == (32, 32):
            filename = "icon_16x16@2x.png"
        elif size == (64, 64):
            filename = "icon_32x32.png"
        elif size == (128, 128):
            filename = "icon_32x32@2x.png"
        elif size == (256, 256):
            filename = "icon_128x128.png"
        elif size == (512, 512):
            filename = "icon_128x128@2x.png"
        elif size == (1024, 1024):
            filename = "icon_256x256@2x.png"
        else:
            continue
        
        filepath = os.path.join(iconset_dir, filename)
        img.save(filepath, 'PNG')
        print(f"✓ Создан: {filename} ({size[0]}x{size[1]})")
    
    # Также создаем icon_256x256.png (для 1x)
    img_256 = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
    draw_256 = ImageDraw.Draw(img_256)
    margin = 16
    draw_256.rounded_rectangle(
        [margin, margin, 256 - margin, 256 - margin],
        radius=32,
        fill=bg_color
    )
    try:
        font_256 = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 150)
    except:
        try:
            font_256 = ImageFont.truetype("/System/Library/Fonts/Arial.ttf", 150)
        except:
            font_256 = ImageFont.load_default()
    
    bbox = draw_256.textbbox((0, 0), "P", font=font_256)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x = (256 - text_width) // 2
    y = (256 - text_height) // 2 - bbox[1]
    draw_256.text((x, y), "P", fill=text_color, font=font_256)
    draw_256.rectangle([margin, 256 - margin - 32, 256 - margin, 256 - margin], fill=accent_color)
    
    filepath_256 = os.path.join(iconset_dir, "icon_256x256.png")
    img_256.save(filepath_256, 'PNG')
    print(f"✓ Создан: icon_256x256.png (256x256)")

def convert_to_icns():
    """Конвертирует iconset в .icns файл"""
    print("\n🔄 Конвертируем в .icns...")
    try:
        result = subprocess.run(
            ['iconutil', '-c', 'icns', 'icon.iconset', '-o', 'icon.icns'],
            check=True,
            capture_output=True,
            text=True
        )
        print("✅ Иконка создана: icon.icns")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка конвертации: {e}")
        print(f"Вывод: {e.stderr}")
        return False

if __name__ == "__main__":
    print("🎨 Создаем иконку для PinMaster...")
    create_icon_images()
    if convert_to_icns():
        print("\n✅ Иконка успешно создана!")
        print("📁 Файл: icon.icns")
        print("🧹 Удаляем временные файлы...")
        import shutil
        if os.path.exists("icon.iconset"):
            shutil.rmtree("icon.iconset")
    else:
        print("\n⚠️ Не удалось создать .icns, но PNG файлы созданы в icon.iconset/")
