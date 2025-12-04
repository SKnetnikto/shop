# utils/image_processor.py
# Логика обработки загруженных изображений товара
# Возвращает имя thumb-файла (например: abc123_thumb.jpg)

import os
import uuid
from PIL import Image
from flask import current_app

def process_product_image(uploaded_file, delete_old_image=None):
    """
    Принимает файл из формы (Flask-WTF FileField)
    Создаёт 3 размера: thumb (300×400), medium (600×800), full (1200×1600)
    Возвращает имя thumb-файла для сохранения в БД
    """
    if not uploaded_file or uploaded_file.filename == '':
        return "placeholder.jpg"

    # Удаляем старые файлы, если передан delete_old_image (при редактировании)
    if delete_old_image and delete_old_image != "placeholder.jpg":
        _delete_old_images(delete_old_image)

    # Генерируем уникальное имя
    unique_id = uuid.uuid4().hex
    base_name = f"{unique_id}"
    upload_folder = current_app.config['UPLOAD_FOLDER']

    # Открываем изображение
    try:
        img = Image.open(uploaded_file)
    except Exception as e:
        raise ValueError("Неподдерживаемый формат изображения")

    # Конвертируем в RGB (важно для JPG)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")

    sizes = {
        'thumb': (300, 400),
        'medium': (600, 800),
        'full': (1200, 1600)
    }

    saved_files = []

    for suffix, size in sizes.items():
        img_copy = img.copy()
        img_copy.thumbnail(size, Image.Resampling.LANCZOS)  # лучший алгоритм

        # Создаём белый фон нужного размера
        background = Image.new('RGB', size, (255, 255, 255))
        offset = ((size[0] - img_copy.width) // 2, (size[1] - img_copy.height) // 2)
        background.paste(img_copy, offset)

        filename = f"{base_name}_{suffix}.jpg"
        save_path = os.path.join(upload_folder, filename)
        background.save(save_path, "JPEG", quality=92, optimize=True)
        saved_files.append(filename)

    return f"{base_name}_thumb.jpg"  # возвращаем только thumb для БД


def _delete_old_images(old_thumb_name):
    """Удаляет все три размера старого изображения"""
    if not old_thumb_name or old_thumb_name == "placeholder.jpg":
        return

    base = old_thumb_name.replace("_thumb.jpg", "")
    suffixes = ["thumb", "medium", "full"]
    for suffix in suffixes:
        old_path = os.path.join(current_app.config['UPLOAD_FOLDER'], f"{base}_{suffix}.jpg")
        try:
            if os.path.exists(old_path):
                os.remove(old_path)
        except:
            pass