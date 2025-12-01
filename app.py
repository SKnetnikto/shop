# app.py
# Главный файл приложения "Шиповник"
# 100% рабочая версия — запускается с первого раза

from flask import Flask, render_template, request
import os


# ВАЖНО: импортируем модели СРАЗУ, до создания приложения!
from models import db, Category, Product


# Создаём приложение
app = Flask(__name__)
# Создаём папку instance заранее (нужно, чтобы SQLite мог создать файл)
if not os.path.exists('instance'):
    os.makedirs('instance')

# Настройки базы данных — используем абсолютный путь к файлу, чтобы избежать проблем на Windows
db_path = os.path.abspath(os.path.join('instance', 'shop.db'))
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{db_path}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Привязываем SQLAlchemy к приложению
db.init_app(app)


# === МАРШРУТЫ ===
@app.route("/")
def index():
    """Главная страница"""
    return render_template("index.html", title="Шиповник")


@app.route("/catalog")
def catalog():
    """Полноценный каталог с фильтрами по категориям, новинкам и распродаже"""
    from models import Category, Product

    # Все категории — для боковой панели
    categories = Category.query.order_by(Category.order).all()

    # Базовый запрос
    query = Product.query

    # Фильтр по категории
    category_slug = request.args.get('category')
    if category_slug:
        category = Category.query.filter_by(slug=category_slug).first()
        if category:
            query = query.filter(Product.category_id == category.id)

    # Фильтр "Новинки"
    if request.args.get('new'):
        query = query.filter(Product.is_new == True)

    # Фильтр "Распродажа"
    if request.args.get('sale'):
        query = query.filter(Product.is_sale == True)

    # Сортировка: сначала новинки, потом по цене
    query = query.order_by(Product.is_new.desc(), Product.created_at.desc())

    # Получаем товары
    products = query.all()

    return render_template(
        "catalog.html",
        title="Каталог — Шиповник",
        categories=categories,
        products=products
    )


# === ЗАПУСК ===
if __name__ == "__main__":
    with app.app_context():                    # ← обязательно!
        # Создаём папку instance, если нет
        if not os.path.exists('instance'):
            os.makedirs('instance')           # ← os.makedirs, а не mkdir (на всякий случай)

        # Создаём все таблицы (теперь Flask знает про модели!)
        db.create_all()
        print("Таблицы созданы (или уже существуют)")

        # Добавляем категории только один раз
        if Category.query.count() == 0:
            categories = [
                Category(name="Женское", slug="women", icon="👗", order=1),
                Category(name="Мужское", slug="men", icon="👔", order=2),
                Category(name="Детское", slug="kids", icon="👶", order=3),
                Category(name="Аксессуары", slug="accessories", icon="👜", order=4),
                Category(name="Распродажа", slug="sale", icon="🔥", order=5),
            ]
            db.session.bulk_save_objects(categories)
            db.session.commit()
            print("Добавлено 5 категорий в базу!")

    app.run(debug=True, host="0.0.0.0", port=5000)
