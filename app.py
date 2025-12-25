# app.py — главный
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


import os
basedir = os.path.abspath(os.path.dirname(__file__))


# ВАЖНО: импорт  СРАЗУ!
from models import db, Category, Product, User, CartItem


# Создаём приложение==============
app = Flask(__name__)

app.config['SECRET_KEY'] = os.urandom(32)
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(basedir, 'instance', 'shop.db')}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'static', 'images', 'products')
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=1)  # 1 день


#  ========лимитер попыток входа   ========
# Ограничение: не более LOGIN_MAX_ATTEMPTS попыток в LOGIN_WINDOW_SECONDS
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 15 * 60  # 15 минут
_login_attempts = defaultdict(list)
_attempts_lock = Lock()

def _prune_attempts(key):
    now = time.time()
    window_start = now - LOGIN_WINDOW_SECONDS
    with _attempts_lock:
        lst = _login_attempts.get(key, [])
        lst = [t for t in lst if t >= window_start]
        if lst:
            _login_attempts[key] = lst
        else:
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
    
    with _attempts_lock:
        lst = _login_attempts.get(key, [])
        if not lst:
            return 0
        earliest = min(lst)
    expires = earliest + LOGIN_WINDOW_SECONDS
    rem = int(expires - time.time())
    return rem if rem > 0 else 0



# делаем папки (потом проверить!)
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
            abort(403)  # облом
        return f(*args, **kwargs)
    return decorated_function

@login_manager.user_loader
def load_user(user_id):
    # Пытаемся найти админа или обычного пользователя
    # Сначала проверяем в таблице админов
    admin = Admin.query.get(int(user_id))
    if admin:
        return admin
    # Если не найден в админах, ищем в обычных пользователях
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
    # Получаем параметры из URL
    category_slug = request.args.get('category')
    show_new = request.args.get('new') == 'true'
    show_sale = request.args.get('sale') == 'true'

    # базовый запрос
    query = Product.query

    # фильтр по категории
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

    # Сортировка сначала по новизне , иначе по дате добавления
    if show_new:
        query = query.order_by(Product.created_at.desc())
    else:
        query = query.order_by(Product.created_at.desc())

    
    products = query.all()

    # Передаём в шаблон
    return render_template(
        "catalog.html",
        products=products,
        current_category=current_category,  # можно использовать в шаблоне
        novelties=show_new  #  уже есть это условие
    )


@app.route('/novelties')
def novelties():
    products = Product.query.order_by(Product.created_at.desc()).limit(10).all()
    return render_template('catalog.html', products=products, novelties=True)
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
        if isinstance(current_user, Admin):
            return redirect("/admin")
        return redirect(url_for('index'))

    form = UserLoginForm()  #  вместо LoginForm
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

        # ищем пользователя среди админов и обычных пользователей
        user = Admin.query.filter_by(username=username).first()
        if not user:
            user = User.query.filter(or_(User.username == username, User.email == username)).first()

        if user and user.check_password(form.password.data):
            #  очищаем счётчики(если получилось)
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

    return render_template("login.html", form=form)





@app.route("/profile")
@login_required
def profile():
    if hasattr(current_user, 'is_admin') and current_user.is_admin():
        return redirect(url_for('admin_panel'))

    # Получаем информацию о пользователе и его заказы/покупки
    user = current_user
    # Можно добавить получение истории заказов или других данных
    return render_template('profile.html', user=user)




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
        # обработка фото — если загружено новое
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
        # форма не прошла валидацию -- показать ошибки
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
        # Используем правильное имя placeholder!
        if product.image != "placeholder.jpg":
            # Удаляем все три размера изображения.
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
       
        # если загружено новое фото — обработать, иначе оставляем старое
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

import os

#   ===================== вспом. функции =================
def get_image_path(base_image_name, size_suffix):
    """
    Возвращает путь к изображению нужного размера, проверяя его существование
    """
    if not base_image_name or base_image_name == "placeholder.jpg":
        return base_image_name

    # Получить имя файла
    if base_image_name.endswith('_thumb.jpg'):
        base_name = base_image_name.replace('_thumb.jpg', '')
    else:
        # если это не thumb-файл, то как есть
        base_name = base_image_name.replace('.jpg', '')

    # Формируем имя файла нужного размера
    target_filename = f"{base_name}_{size_suffix}.jpg"

    # Проверить, существует ли файл в папке загрузки
    upload_folder = app.config['UPLOAD_FOLDER']
    full_path = os.path.join(upload_folder, target_filename)

    # Если файл существует, то вернем его имя, иначе возвращаем оригинальное
    if os.path.exists(full_path):
        return target_filename
    else:
        # Если файл нужного размера не существует, возвращаем оригинальное имя
        # или возвращаем thumb, если запрашиваемый размер не thumb
        if size_suffix != 'thumb' and base_image_name.endswith('_thumb.jpg'):
            return base_image_name  # возвращаем thumb, если запрашиваемый размер отсутствует
        return base_image_name

# ===================== КОНТЕКСТНЫЙ ПРОЦЕССОР =====================
# Делает переменную categories доступной ВО ВСЕХ шаблонах автоматически
@app.context_processor
def inject_categories():
    """
    Добавляет в каждый шаблон список категорий из базы.
    Теперь можно использовать {{ categories }} и Category в любом .html
    """
    categories = Category.query.order_by(Category.order).all()
    return dict(categories=categories, get_image_path=get_image_path)

# ===================== КОРЗИНА =====================
@app.route("/cart")
@login_required
def cart():
    # Получаем все товары пользователя из корзины
    cart_items = CartItem.query.filter_by(user_id=current_user.id).all()

    # если корзина пуста, показывать пустую корзину
    if not cart_items:
        return render_template("cart.html", cart_items=[], total=0)

    # Рассчитываем общую сумму
    total = sum(item.product.price * item.quantity for item in cart_items)

    return render_template("cart.html", cart_items=cart_items, total=total)

@app.route("/cart/add/<int:product_id>", methods=["POST", "GET"])
@login_required
def add_to_cart(product_id):
    product = Product.query.get_or_404(product_id)

    # Получаем размер из формы
    size = request.form.get('size') if request.method == 'POST' else None

    # Проверяем, что если у товара есть размеры, то пользователь выбрал один из них
    if product.sizes:  # Если у товара есть доступные размеры
        if not size:  # Если размер не выбран
            flash(f"Пожалуйста, выберите размер для товара «{product.title}»", "error")
            return redirect(request.referrer or url_for('catalog'))

        # Проверяем, что размер доступен для этого товара
        available_sizes = [s.strip() for s in product.sizes.split(',')]
        if size not in available_sizes:
            flash(f"Размер {size} недоступен для этого товара", "error")
            return redirect(request.referrer or url_for('catalog'))

    cart_item = CartItem.query.filter_by(
        user_id=current_user.id,
        product_id=product_id,
        size=size
    ).first()

    if cart_item:
        # Товар уже есть — увеличиваем количество и показываем сообщение
        cart_item.quantity += 1
        db.session.commit()
        size_text = f" (размер {size})" if size else ""
        flash(f"Товар «{product.title}»{size_text} уже в корзине. Количество увеличено до {cart_item.quantity} шт.", "info")
    else:
        # Новый товар
        cart_item = CartItem(
            user_id=current_user.id,
            product_id=product_id,
            size=size,
            quantity=1
        )
        db.session.add(cart_item)
        db.session.commit()
        size_text = f" (размер {size})" if size else ""
        flash(f"Товар «{product.title}»{size_text} добавлен в корзину!", "success")

    # Остаёмся на той же странице 
    return redirect(request.referrer or url_for('catalog'))

@app.route("/cart/update/<int:cart_item_id>", methods=["POST"])
@login_required
def update_cart_item(cart_item_id):
    cart_item = CartItem.query.get_or_404(cart_item_id)

    if cart_item.user_id != current_user.id:
        flash("У вас нет прав на изменение этой корзины", "error")
        return redirect(url_for("cart"))

    quantity = int(request.form.get("quantity", 1))

    if quantity <= 0:
        size_text = f" (размер {cart_item.size})" if cart_item.size else ""
        db.session.delete(cart_item)
        flash(f"Товар «{cart_item.product.title}»{size_text} удалён из корзины", "info")
    else:
        cart_item.quantity = quantity
        size_text = f" (размер {cart_item.size})" if cart_item.size else ""
        flash(f"Количество товара «{cart_item.product.title}»{size_text} обновлено: {quantity} шт.", "success")

    db.session.commit()
    return redirect(url_for("cart"))

@app.route("/cart/remove/<int:cart_item_id>", methods=["POST"])
@login_required
def remove_from_cart(cart_item_id):
    cart_item = CartItem.query.get_or_404(cart_item_id)

    # Проверить что товар принадлежит текущему пользователю
    if cart_item.user_id != current_user.id:
        flash("У вас нет прав на удаление из этой корзины", "error")
        return redirect(url_for("cart"))

    product_title = cart_item.product.title
    size_text = f" (размер {cart_item.size})" if cart_item.size else ""
    db.session.delete(cart_item)
    db.session.commit()
    flash(f"Товар «{product_title}»{size_text} удален из корзины", "info")
    return redirect(url_for("cart"))

# =====    поиск   =====================
@app.route('/search')
def search():
    q = request.args.get('q', '').strip()
    category_slug = request.args.get('category')
    min_price = request.args.get('min_price')
    max_price = request.args.get('max_price')
    new = request.args.get('new')
    sale = request.args.get('sale')

    # Новые параметры для атр поиска
    brand = request.args.get('brand')
    color = request.args.get('color')
    size = request.args.get('size')
    tag = request.args.get('tag')

    
    products_q = Product.query.filter(Product.in_stock == True)

    # поиск по тексту
    if q:
        query_lower = q.lower()
        products_q = products_q.filter(
            Product.search_text.like(f"%{query_lower}%")
        )

    # фильтр по категории
    if category_slug:
        category = Category.query.filter_by(slug=category_slug).first()
        if category:
            products_q = products_q.filter(Product.category_id == category.id)

    # Фильтр по цене
    if min_price:
        try:
            min_val = float(min_price)
            products_q = products_q.filter(Product.price >= min_val)
        except (ValueError, TypeError):
            pass  # игнорировать некорректные значения

    if max_price:
        try:
            max_val = float(max_price)
            products_q = products_q.filter(Product.price <= max_val)
        except (ValueError, TypeError):
            pass

    # Фильтр по атрибутам
    if brand:
        products_q = products_q.filter(Product.brand.ilike(f"%{brand}%"))

    if color:
        products_q = products_q.filter(Product.color.ilike(f"%{color}%"))

    if size:
        # Поиск размера в строке sizes 
        products_q = products_q.filter(Product.sizes.ilike(f"%{size}%"))

    if tag:
        # Поиск тега в строке tags .
        products_q = products_q.filter(Product.tags.ilike(f"%{tag}%"))

    # Флаги: новинки и распродажа
    if new:
        products_q = products_q.filter(Product.is_new == True)
    if sale:
        products_q = products_q.filter(Product.is_sale == True)

    
    products = products_q.order_by(Product.created_at.desc()).all()

    return render_template('search_results.html', products=products, q=q)

@app.route('/product/<int:product_id>')
def product(product_id):
    product = Product.query.get_or_404(product_id)
    return render_template('product_detail.html', product=product)

@app.route('/about')
def about():
    return render_template('about.html')

#                         ===================== ЗАПУСК =====================
if __name__ == "__main__":
    with app.app_context():
        # Создаем все таблицы
        db.create_all()

        # Проверяем и добавляем недостающий столбец size в таблицу cart_item
        try:
            # Проверяем, существует ли столбец size
            result = db.session.execute(db.text("PRAGMA table_info(cart_item)")).fetchall()
            column_names = [row[1] for row in result]

            if 'size' not in column_names:
                # Добавляем столбец size
                db.session.execute(db.text("ALTER TABLE cart_item ADD COLUMN size VARCHAR(20)"))
                db.session.commit()
                print("Добавлен столбец size в таблицу cart_item")
        except Exception as e:
            print(f"Ошибка при добавлении столбца: {e}")
            db.session.rollback()

        # Проверка наличия placeholder
        placeholder_path = os.path.join(basedir, 'static', 'images', 'placeholder.jpg')
        if not os.path.exists(placeholder_path):
            print("WARNING: placeholder image not found:", placeholder_path)

        # Создаём админа !!!  ---КСЯК исправить
        if not Admin.query.first():
            admin = Admin(username="admin")
            admin.set_password("admin")  # потом сменить пароль!
            db.session.add(admin)
            db.session.commit()
            print("Админ создан: admin / admin")

        # категории
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
