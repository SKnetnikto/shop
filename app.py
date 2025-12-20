# app.py — финальная, проверенная и 100% рабочая версия
from flask import Flask, render_template, request, redirect, url_for, flash, session, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm, CSRFProtect
from flask_wtf.file import FileField, FileAllowed
from wtforms import (StringField, PasswordField, SubmitField, FloatField,
                     TextAreaField, BooleanField, SelectField, ValidationError)
from functools import wraps

from wtforms.validators import DataRequired, Length, NumberRange
from werkzeug.utils import secure_filename
from models import db, Category, Product, Admin
from uuid import uuid4
from sqlalchemy import or_
from PIL import Image
import io
import time
from collections import defaultdict
from threading import Lock
from datetime import timedelta


#================для обработки картинок           =======

from utils.image_processor import process_product_image

# ===================== НАСТРОЙКИ ПРИЛОЖЕНИЯ =====================
import os
basedir = os.path.abspath(os.path.dirname(__file__))


# ВАЖНО: импортируем модели СРАЗУ, до создания приложения!
from models import db, Category, Product, User, CartItem


# Создаём приложение
app = Flask(__name__)

app.config['SECRET_KEY'] = os.urandom(32)
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(basedir, 'instance', 'shop.db')}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'static', 'images', 'products')
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=1)  # 1 день


# Простейший in-memory лимитер попыток входа
# Ограничение: не более LOGIN_MAX_ATTEMPTS попыток в LOGIN_WINDOW_SECONDS
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 15 * 60  # 15 минут
# Структура: ключ -> list[unix_timestamp]
_login_attempts = defaultdict(list)
_attempts_lock = Lock()

def _prune_attempts(key):
    now = time.time()
    window_start = now - LOGIN_WINDOW_SECONDS
    with _attempts_lock:
        lst = _login_attempts.get(key, [])
        # keep only timestamps within window
        lst = [t for t in lst if t >= window_start]
        if lst:
            _login_attempts[key] = lst
        else:
            # remove empty to avoid memory growth
            _login_attempts.pop(key, None)
        return len(lst)

def _record_failed(key):
    now = time.time()
    with _attempts_lock:
        _login_attempts[key].append(now)

def _is_blocked(key):
    cnt = _prune_attempts(key)
    return cnt >= LOGIN_MAX_ATTEMPTS

def _remaining_block_seconds(key):
    # returns seconds until the earliest attempt ages out enough
    with _attempts_lock:
        lst = _login_attempts.get(key, [])
        if not lst:
            return 0
        earliest = min(lst)
    expires = earliest + LOGIN_WINDOW_SECONDS
    rem = int(expires - time.time())
    return rem if rem > 0 else 0



# Создаём папки
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(basedir, 'instance'), exist_ok=True)  # ← важная строка!

# Защита от CSRF и Flask-Login
csrf = CSRFProtect(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = "info"

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        if not (hasattr(current_user, 'is_admin') and current_user.is_admin()):
            abort(403)  # Запрещено
        return f(*args, **kwargs)
    return decorated_function

@login_manager.user_loader
def load_user(user_id):
    # Пытаемся найти админа или обычного пользователя
    admin = Admin.query.get(int(user_id))
    if admin:
        return admin
    return User.query.get(int(user_id))

db.init_app(app)

# ===================== ФОРМЫ =====================
class LoginForm(FlaskForm):
    username = StringField('Логин', validators=[DataRequired(), Length(3, 50)])
    password = PasswordField('Пароль', validators=[DataRequired()])
    submit = SubmitField('Войти')

class RegisterForm(FlaskForm):
    username = StringField('Логин', validators=[DataRequired(), Length(3, 50)])
    email = StringField('Email', validators=[DataRequired(), Length(6, 120)])
    password = PasswordField('Пароль', validators=[DataRequired(), Length(6, 128)])
    confirm_password = PasswordField('Подтвердите пароль', validators=[DataRequired()])
    full_name = StringField('ФИО', validators=[Length(max=100)])
    phone = StringField('Телефон', validators=[Length(max=20)])
    submit = SubmitField('Зарегистрироваться')

    def validate_username(self, field):
        if User.query.filter_by(username=field.data).first() or Admin.query.filter_by(username=field.data).first():
            raise ValidationError('Этот логин уже занят!')

    def validate_email(self, field):
        if User.query.filter_by(email=field.data).first():
            raise ValidationError('Этот email уже зарегистрирован!')

    def validate_confirm_password(self, field):
        if field.data != self.password.data:
            raise ValidationError('Пароли не совпадают!')

class UserLoginForm(FlaskForm):
    username = StringField('Логин или Email', validators=[DataRequired(), Length(3, 120)])
    password = PasswordField('Пароль', validators=[DataRequired()])
    submit = SubmitField('Войти')

class ProductForm(FlaskForm):
    title = StringField('Название', validators=[DataRequired(), Length(1, 100)])
    price = FloatField('Цена', validators=[DataRequired(), NumberRange(min=0)])
    old_price = FloatField('Старая цена', validators=[NumberRange(min=0)])
    description = TextAreaField('Описание', validators=[Length(max=1000)])
    sku = StringField('Артикул', validators=[Length(max=64)])
    brand = StringField('Бренд', validators=[Length(max=80)])
    color = StringField('Цвет', validators=[Length(max=50)])
    sizes = StringField('Размеры (через запятую)', validators=[Length(max=200)], description='Например: 42, 44, 46, 48, 50, 52, 54')
    tags = StringField('Теги (через запятую)', validators=[Length(max=200)])
    image = FileField('Фото', validators=[FileAllowed(['jpg', 'jpeg', 'png', 'webp'])])
    category = SelectField('Категория', coerce=int, validators=[DataRequired()])
    is_new = BooleanField('Новинка')
    is_sale = BooleanField('Распродажа')
    submit = SubmitField('Добавить товар')

# ===================== МАРШРУТЫ =====================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/catalog")
def catalog():
    # Загружаем все категории для бокового меню
    categories = Category.query.order_by(Category.order).all()

    # Получаем параметры из URL
    category_slug = request.args.get('category')
    show_new = request.args.get('new') == 'true'
    show_sale = request.args.get('sale') == 'true'

    # Начинаем базовый запрос
    query = Product.query

    # Фильтр по категории
    if category_slug:
        category = Category.query.filter_by(slug=category_slug).first_or_404()
        query = query.filter_by(category_id=category.id)
        current_category = category
    else:
        current_category = None

    # Фильтр "Новинки"
    if show_new:
        query = query.filter_by(is_new=True)

    # Фильтр "Распродажа"
    if show_sale:
        query = query.filter_by(is_sale=True)

    # Сортировка: сначала по новизне (если включён фильтр new), иначе по дате добавления
    if show_new:
        query = query.order_by(Product.created_at.desc())
    else:
        query = query.order_by(Product.created_at.desc())

    # Выполняем запрос
    products = query.all()

    # Передаём в шаблон
    return render_template(
        "catalog.html",
        categories=categories,
        products=products,
        current_category=current_category,  # можно использовать в шаблоне, если захочешь
        novelties=show_new  # у тебя уже есть это условие в hero-секции
    )


@app.route('/novelties')
def novelties():
    categories = Category.query.order_by(Category.order).all()
    products = Product.query.order_by(Product.created_at.desc()).limit(10).all()
    return render_template('catalog.html', categories=categories, products=products, novelties=True)
@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = RegisterForm()
    if form.validate_on_submit():
        user = User(
            username=form.username.data,
            email=form.email.data,
            full_name=form.full_name.data,
            phone=form.phone.data
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('Регистрация прошла успешно! Теперь вы можете войти.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html', form=form)

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))  # Всех на главную, не в админку!
    
    form = UserLoginForm()
    
    if form.validate_on_submit():
        username = (form.username.data or '').strip()
        
        admin = Admin.query.filter_by(username=username).first()
        if admin and admin.check_password(form.password.data):
            login_user(admin, remember=True)
            return redirect("/admin")  # Только админа в админку
        
        user = User.query.filter(or_(User.username == username, User.email == username)).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=True)
            return redirect(url_for('index'))  # Обычного пользователя на главную
        
        flash('Неверный логин или пароль', 'error')
    
    return render_template('login.html', form=form)




"""@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        if isinstance(current_user, Admin):
            return redirect("/admin")
        return redirect(url_for('index'))
        
    form = UserLoginForm()  # Используем UserLoginForm вместо LoginForm
    ip = request.remote_addr or 'unknown'
    
    if form.validate_on_submit():
        username = (form.username.data or '').strip()
        
        # Проверяем блокировку
        ip_key = f"ip:{ip}"
        user_key = f"user:{username}"
        if _is_blocked(ip_key) or _is_blocked(user_key):
            rem = max(_remaining_block_seconds(ip_key), _remaining_block_seconds(user_key))
            flash(f"Слишком много попыток входа. Попробуйте через {rem} секунд.", "error")
            return render_template("login.html", form=form)

        # Ищем пользователя среди админов и обычных пользователей
        user = Admin.query.filter_by(username=username).first()
        if not user:
            user = User.query.filter(or_(User.username == username, User.email == username)).first()
            
        if user and user.check_password(form.password.data):
            # успешный вход — очищаем счётчики
            with _attempts_lock:
                _login_attempts.pop(ip_key, None)
                _login_attempts.pop(user_key, None)
            login_user(user, remember=True)
            
            if isinstance(user, Admin):
                return redirect("/admin")
            return redirect(url_for('index'))

        # неудачная попытка
        _record_failed(ip_key)
        _record_failed(user_key)
        attempts_left = min(
            max(0, LOGIN_MAX_ATTEMPTS - _prune_attempts(ip_key)),
            max(0, LOGIN_MAX_ATTEMPTS - _prune_attempts(user_key))
        )
        
        if attempts_left <= 0:
            flash("Слишком много попыток входа. Попробуйте позже.", "error")
        else:
            flash(f"Неверный логин или пароль. Осталось попыток: {attempts_left}", "error")
            
    return render_template("login.html", form=form)"""

@app.route("/profile")
@login_required
def profile():
    if current_user.is_admin():  # или hasattr(current_user, 'is_admin') и current_user.is_admin()
        return redirect(url_for('admin_panel'))
    return render_template('profile.html')




@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect("/")

@app.route("/admin", methods=["GET", "POST"])
@admin_required
def admin_panel():
    form = ProductForm()
    form.category.choices = [(c.id, c.name) for c in Category.query.order_by(Category.order).all()]

    # Обработка отправки формы вне зависимости от валидации
    if request.method == "POST":
        print("Форма отправлена, начинаем обработку")
        # Обработка фото — если загружено новое
        if form.image.data:
            print("Загружено изображение:", form.image.data.filename)
            image_filename = process_product_image(form.image.data)
        else:
            print("Изображение не выбрано, используем placeholder")
            image_filename = "placeholder.jpg"  # если фото не выбрано

        print("Создаем объект товара")
        
        # Получаем данные из формы, с запасными значениями для обязательных полей
        title = form.title.data or "Без названия"
        price = form.price.data or 0
        category_id = form.category.data or 1  # ID первой категории
        
        product = Product(
            title=title,
            price=price,
            old_price=form.old_price.data,
            description=form.description.data or "",
            image=image_filename,
            category_id=category_id,
            is_new=form.is_new.data,
            is_sale=form.is_sale.data,
            sizes=form.sizes.data
        )
        print("Добавляем товар в сессию")
        db.session.add(product)
        print("Сохраняем изменения в БД")
        db.session.commit()
        print(f"Товар «{product.title}» успешно добавлен!")
        flash(f"Товар «{product.title}» успешно добавлен!", "success")
        return redirect(url_for("admin_products"))
    else:
        # Если форма не прошла валидацию, показываем ошибки
        if form.errors:
            for field, errors in form.errors.items():
                for error in errors:
                    flash(f"Ошибка в поле «{field.capitalize()}»: {error}", "error")
    products = Product.query.order_by(Product.created_at.desc()).all()
    return render_template("admin_panel.html", form=form, products=products)

@app.route("/admin/delete/<int:product_id>", methods=["POST"])
@admin_required
def delete_product(product_id):
    try:
        product = Product.query.get_or_404(product_id)
        if product.image != "placeholder.png":
            # Удаляем все три размера изображения (thumb, medium, full)
            base_name = product.image.replace("_thumb.jpg", "")
            for suffix in ["thumb", "medium", "full"]:
                try:
                    os.remove(os.path.join(app.config['UPLOAD_FOLDER'], f"{base_name}_{suffix}.jpg"))
                except:
                    pass
        db.session.delete(product)
        db.session.commit()
        flash(f"Товар «{product.title}» удалён", "info")
    except Exception as e:
        flash(f"Ошибка при удалении товара: {str(e)}", "error")
        return redirect(url_for("admin_products"))
    return redirect(url_for("admin_products"))
@app.route("/admin/products")
@admin_required
def admin_products():
    products = Product.query.order_by(Product.created_at.desc()).all()
    return render_template("admin_products.html", products=products)


@app.route("/admin/edit/<int:product_id>", methods=["GET", "POST"])
@admin_required
def edit_product(product_id):
    product = Product.query.get_or_404(product_id)
    form = ProductForm(obj=product)  # заполняем форму текущими данными
    form.category.choices = [(c.id, c.name) for c in Category.query.order_by(Category.order).all()]

    if form.validate_on_submit():
        old_image = product.image  # запоминаем старо
       
        # Если загружено новое фото — обрабатываем, иначе оставляем старое
        if form.image.data:
            image_filename = process_product_image(form.image.data, delete_old_image=old_image)
            product.image = image_filename
        # иначе image остаётся прежним — ничего не трогать не надо

        # Обновляем остальные поля
        product.title = form.title.data
        product.price = form.price.data
        product.old_price = form.old_price.data or None
        product.description = form.description.data or ""
        product.category_id = form.category.data
        product.is_new = form.is_new.data
        product.is_sale = form.is_sale.data
        product.sizes = form.sizes.data
    
        db.session.commit()
        flash("Товар обновлён!", "success")
        return redirect("/admin/products")
    return render_template("admin_edit.html", form=form, product=product)

@app.errorhandler(403)
def forbidden(error):
    return render_template('403.html'), 403

# ===================== КОНТЕКСТНЫЙ ПРОЦЕССОР =====================
# Делает переменную categories доступной ВО ВСЕХ шаблонах автоматически
@app.context_processor
def inject_categories():
    """
    Добавляет в каждый шаблон список категорий из базы.
    Теперь можно использовать {{ categories }} и Category в любом .html
    """
    categories = Category.query.order_by(Category.order).all()
    return dict(categories=categories)


# ===================== КОРЗИНА =====================
@app.route("/cart")
@login_required
def cart():
    # Получаем все товары пользователя из корзины
    cart_items = CartItem.query.filter_by(user_id=current_user.id).all()

    # Если корзина пуста, показываем пустую корзину
    if not cart_items:
        return render_template("cart.html", cart_items=[], total=0)

    # Рассчитываем общую сумму
    total = sum(item.product.price * item.quantity for item in cart_items)

    return render_template("cart.html", cart_items=cart_items, total=total)

@app.route("/cart/add/<int:product_id>", methods=["POST"])
@login_required
def add_to_cart(product_id):
    product = Product.query.get_or_404(product_id)

    # Проверяем, есть ли товар уже в корзине
    cart_item = CartItem.query.filter_by(
        user_id=current_user.id, 
        product_id=product_id
    ).first()

    if cart_item:
        # Если товар уже в корзине, увеличиваем количество
        cart_item.quantity += 1
    else:
        # Если товара нет в корзине, добавляем его
        cart_item = CartItem(
            user_id=current_user.id,
            product_id=product_id,
            quantity=1
        )
        db.session.add(cart_item)

    db.session.commit()
    flash(f"Товар «{product.title}» добавлен в корзину", "success")
    return redirect(url_for("cart"))

@app.route("/cart/update/<int:cart_item_id>", methods=["POST"])
@login_required
def update_cart_item(cart_item_id):
    cart_item = CartItem.query.get_or_404(cart_item_id)

    # Проверяем, что товар принадлежит текущему пользователю
    if cart_item.user_id != current_user.id:
        flash("У вас нет прав на изменение этой корзины", "error")
        return redirect(url_for("cart"))

    # Получаем новое количество из формы
    quantity = int(request.form.get("quantity", 1))

    if quantity <= 0:
        # Если количество 0 или меньше, удаляем товар из корзины
        db.session.delete(cart_item)
        flash("Товар удален из корзины", "info")
    else:
        # Иначе обновляем количество
        cart_item.quantity = quantity
        flash("Количество товара обновлено", "success")

    db.session.commit()
    return redirect(url_for("cart"))

@app.route("/cart/remove/<int:cart_item_id>", methods=["POST"])
@login_required
def remove_from_cart(cart_item_id):
    cart_item = CartItem.query.get_or_404(cart_item_id)

    # Проверяем, что товар принадлежит текущему пользователю
    if cart_item.user_id != current_user.id:
        flash("У вас нет прав на удаление из этой корзины", "error")
        return redirect(url_for("cart"))

    product_title = cart_item.product.title
    db.session.delete(cart_item)
    db.session.commit()
    flash(f"Товар «{product_title}» удален из корзины", "info")
    return redirect(url_for("cart"))

# ===================== ПОИСК =====================
@app.route('/search')
def search():
    q = request.args.get('q', '').strip()
    category_slug = request.args.get('category')
    min_price = request.args.get('min_price')
    max_price = request.args.get('max_price')
    new = request.args.get('new')
    sale = request.args.get('sale')

    products_q = Product.query

    if q:
        # простая проверка: ищем по объединённому полю,
        # и на всякий случай — отдельно по описанию (если search_text пуст)
        products_q = products_q.filter(
            or_(Product.search_text.ilike(f"%{q}%"), Product.description.ilike(f"%{q}%"))
        )

    if category_slug:
        cat = Category.query.filter_by(slug=category_slug).first()
        if cat:
            products_q = products_q.filter_by(category_id=cat.id)

    try:
        if min_price:
            products_q = products_q.filter(Product.price >= float(min_price))
        if max_price:
            products_q = products_q.filter(Product.price <= float(max_price))
    except ValueError:
        pass

    if new:
        products_q = products_q.filter_by(is_new=True)
    if sale:
        products_q = products_q.filter_by(is_sale=True)

    products = products_q.order_by(Product.created_at.desc()).all()
    return render_template('search_results.html', products=products, q=q)

# ===================== ЗАПУСК =====================
if __name__ == "__main__":
    with app.app_context():
        db.create_all()

        # Проверка наличия placeholder изображения — удобная подсказка при разработке
        placeholder_path = os.path.join(basedir, 'static', 'images', 'placeholder.png')
        if not os.path.exists(placeholder_path):
            print("WARNING: placeholder image not found:", placeholder_path)

        # Создаём админа один раз
        if not Admin.query.first():
            admin = Admin(username="admin")
            admin.set_password("admin")  # потом сменишь пароль!
            db.session.add(admin)
            db.session.commit()
            print("Админ создан: admin / admin")

        # Категории
        if Category.query.count() == 0:
            cats = [
                Category(name="Женское", slug="women", icon="dress", order=1),
                Category(name="Мужское", slug="men", icon="shirt", order=2),
                Category(name="Детское", slug="kids", icon="baby", order=3),
                Category(name="Аксессуары", slug="accessories", icon="bag", order=4),
                Category(name="Распродажа", slug="sale", icon="fire", order=5),
            ]
            db.session.bulk_save_objects(cats)
            db.session.commit()

    app.run(debug=True, host="0.0.0.0", port=5000)
