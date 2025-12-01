# models.py
# Здесь живут все модели базы данных для магазина "Шиповник"
# Используем Flask-SQLAlchemy — удобно, красиво и надёжно

from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

# Создаём объект БД. Подключим его в app.py чуть позже
db = SQLAlchemy()


class Category(db.Model):
    """
    Модель категории товаров (Женское, Мужское, Детское и т.д.)
    """
    __tablename__ = 'category'                  # имя таблицы в базе

    id = db.Column(db.Integer, primary_key=True)        # уникальный ID
    name = db.Column(db.String(50), unique=True, nullable=False)  # название, например "Женское"
    slug = db.Column(db.String(50), unique=True, nullable=False)  # для URL: /category/women
    icon = db.Column(db.String(20), default="👗")       # эмодзи-иконка для красоты
    order = db.Column(db.Integer, default=0)            # для сортировки в меню

    # Связь с товарами (одна категория — много товаров)
    products = db.relationship('Product', backref='category', lazy=True)

    def __repr__(self):
        return f"<Category {self.name}>"



class Admin(UserMixin, db.Model):
    """
    Модель администратора — только один пользователь
    """
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)

    def set_password(self, password):
        """Хешируем пароль при создании/смене"""
        self.password_hash = generate_password_hash(password, method='scrypt')

    def check_password(self, password):
        """Проверяем пароль при входе"""
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<Admin {self.username} >"


class Product(db.Model):
    """
    Модель товара в магазине
    """
    __tablename__ = 'product'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)          # название товара
    price = db.Column(db.Float, nullable=False)                 # цена в рублях
    old_price = db.Column(db.Float, nullable=True)              # старая цена (для скидок)
    description = db.Column(db.Text, nullable=True)             # описание
    image = db.Column(db.String(100), default="placeholder.jpg") # имя файла картинки
    in_stock = db.Column(db.Boolean, default=True)              # есть ли в наличии
    is_new = db.Column(db.Boolean, default=False)               # новинка?
    is_sale = db.Column(db.Boolean, default=False)              # на распродаже?

    # Внешний ключ — связь с категорией
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)

    # Дата добавления (для сортировки "новинки")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Product {self.title}>"

    # Удобное свойство: скидка в процентах
    @property
    def discount_percent(self):
        if self.old_price and self.old_price > self.price:
            return round((1 - self.price / self.old_price) * 100)
        return 0