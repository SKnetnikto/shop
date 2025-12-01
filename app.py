# app.py — финальная, проверенная и 100% рабочая версия
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm, CSRFProtect
from flask_wtf.file import FileField, FileAllowed
from wtforms import (StringField, PasswordField, SubmitField, FloatField,
                     TextAreaField, BooleanField, SelectField)
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

# ===================== НАСТРОЙКИ ПРИЛОЖЕНИЯ =====================
import os
basedir = os.path.abspath(os.path.dirname(__file__))


# ВАЖНО: импортируем модели СРАЗУ, до создания приложения!
from models import db, Category, Product


# Создаём приложение
app = Flask(__name__)

app.config['SECRET_KEY'] = os.urandom(32)
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(basedir, 'instance', 'shop.db')}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'static', 'images', 'products')
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'webp', 'gif'}

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

@login_manager.user_loader
def load_user(user_id):
    return Admin.query.get(int(user_id))

db.init_app(app)

# ===================== ФОРМЫ =====================
class LoginForm(FlaskForm):
    username = StringField('Логин', validators=[DataRequired(), Length(3, 50)])
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
    categories = Category.query.order_by(Category.order).all()
    products = Product.query.order_by(Product.created_at.desc()).all()
    return render_template("catalog.html", categories=categories, products=products)


@app.route('/novelties')
def novelties():
    categories = Category.query.order_by(Category.order).all()
    products = Product.query.order_by(Product.created_at.desc()).limit(10).all()
    return render_template('catalog.html', categories=categories, products=products, novelties=True)

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect("/admin")
    form = LoginForm()
    ip = request.remote_addr or 'unknown'
    if form.validate_on_submit():
        username = (form.username.data or '').strip()

        # Проверяем блокировку по IP или по имени пользователя
        ip_key = f"ip:{ip}"
        user_key = f"user:{username}"
        if _is_blocked(ip_key) or _is_blocked(user_key):
            rem = max(_remaining_block_seconds(ip_key), _remaining_block_seconds(user_key))
            flash(f"Слишком много попыток входа. Попробуйте через {rem} секунд.", "error")
            return render_template("admin_login.html", form=form)

        user = Admin.query.filter_by(username=username).first()
        if user and user.check_password(form.password.data):
            # успешный вход — очищаем счётчики
            with _attempts_lock:
                _login_attempts.pop(ip_key, None)
                _login_attempts.pop(user_key, None)
            login_user(user)
            return redirect("/admin")

        # неудачная попытка — записать для IP и пользователя
        _record_failed(ip_key)
        _record_failed(user_key)
        # сообщаем пользователю
        attempts_left_ip = max(0, LOGIN_MAX_ATTEMPTS - _prune_attempts(ip_key))
        attempts_left_user = max(0, LOGIN_MAX_ATTEMPTS - _prune_attempts(user_key))
        attempts_left = min(attempts_left_ip, attempts_left_user)
        if attempts_left <= 0:
            flash("Слишком много попыток входа. Попробуйте позже.", "error")
        else:
            flash(f"Неверный логин или пароль. Осталось попыток: {attempts_left}", "error")
    return render_template("admin_login.html", form=form)

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect("/")

@app.route("/admin", methods=["GET", "POST"])
@login_required
def admin_panel():
    form = ProductForm()
    form.category.choices = [(c.id, c.name) for c in Category.query.order_by(Category.order).all()]

    if form.validate_on_submit():
        filename = "placeholder.png"
        if form.image.data:
            # process and save multiple sizes, return the main filename (800px)
            orig = secure_filename(form.image.data.filename)
            base = uuid4().hex
            def save_image_variants(file_storage, base_name):
                try:
                    img = Image.open(file_storage.stream)
                except Exception:
                    file_storage.stream.seek(0)
                    img = Image.open(file_storage.stream)

                sizes = (400, 800, 1600)
                for w in sizes:
                    # don't upscale small images
                    if img.width <= w:
                        out = img.copy()
                    else:
                        ratio = w / img.width
                        h = int(img.height * ratio)
                        out = img.resize((w, h), Image.LANCZOS)

                    # convert to RGB (no alpha) for JPEG/WebP
                    if out.mode in ("RGBA", "LA"):
                        bg = Image.new("RGB", out.size, (255, 255, 255))
                        bg.paste(out, mask=out.split()[-1])
                        out_rgb = bg
                    else:
                        out_rgb = out.convert("RGB")

                    jpg_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{base_name}-{w}.jpg")
                    webp_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{base_name}-{w}.webp")
                    out_rgb.save(jpg_path, "JPEG", quality=85, optimize=True)
                    try:
                        out_rgb.save(webp_path, "WEBP", quality=80, method=6)
                    except Exception:
                        # some Pillow builds may not support method arg
                        out_rgb.save(webp_path, "WEBP", quality=80)

                # return the canonical main filename (800px jpg)
                return f"{base_name}-800.jpg"

            filename = save_image_variants(form.image.data, base)

        product = Product(
            title=form.title.data,
            price=form.price.data,
            old_price=form.old_price.data or None,
            description=form.description.data or "",
            sku=form.sku.data or None,
            brand=form.brand.data or None,
            color=form.color.data or None,
            tags=form.tags.data or "",
            image=filename,
            category_id=form.category.data,
            is_new=form.is_new.data,
            is_sale=form.is_sale.data
        )
        # Формируем объединённый текст для быстрого поиска
        product.search_text = ' '.join(filter(None, [product.title, product.description, product.tags, product.brand, product.color, product.sku]))
        db.session.add(product)
        db.session.commit()
        flash(f"Товар «{product.title}» добавлен!", "success")
        return redirect("/admin")

    products = Product.query.order_by(Product.created_at.desc()).all()
    return render_template("admin_panel.html", form=form, products=products)

@app.route("/admin/delete/<int:product_id>", methods=["POST"])
@login_required
def delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    if product.image != "placeholder.png":
        try:
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], product.image))
        except:
            pass
    db.session.delete(product)
    db.session.commit()
    flash("Товар удалён", "info")
    return redirect("/admin")
@app.route("/admin/products")
@login_required
def admin_products():
    products = Product.query.order_by(Product.created_at.desc()).all()
    return render_template("admin_products.html", products=products)


@app.route("/admin/edit/<int:product_id>", methods=["GET", "POST"])
@login_required
def edit_product(product_id):
    product = Product.query.get_or_404(product_id)
    form = ProductForm(obj=product)  # заполняем форму текущими данными
    form.category.choices = [(c.id, c.name) for c in Category.query.order_by(Category.order).all()]

    if form.validate_on_submit():
        # Обновляем данные
        product.title = form.title.data
        product.price = form.price.data
        product.old_price = form.old_price.data or None
        product.description = form.description.data or ""
        product.category_id = form.category.data
        product.is_new = form.is_new.data
        product.is_sale = form.is_sale.data

        # Если загружено новое фото — заменяем
        if form.image.data:
            base = uuid4().hex
            # save new variants
            def save_image_variants_inline(file_storage, base_name):
                try:
                    img = Image.open(file_storage.stream)
                except Exception:
                    file_storage.stream.seek(0)
                    img = Image.open(file_storage.stream)
                sizes = (400, 800, 1600)
                for w in sizes:
                    if img.width <= w:
                        out = img.copy()
                    else:
                        ratio = w / img.width
                        h = int(img.height * ratio)
                        out = img.resize((w, h), Image.LANCZOS)
                    if out.mode in ("RGBA", "LA"):
                        bg = Image.new("RGB", out.size, (255, 255, 255))
                        bg.paste(out, mask=out.split()[-1])
                        out_rgb = bg
                    else:
                        out_rgb = out.convert("RGB")
                    jpg_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{base_name}-{w}.jpg")
                    webp_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{base_name}-{w}.webp")
                    out_rgb.save(jpg_path, "JPEG", quality=85, optimize=True)
                    try:
                        out_rgb.save(webp_path, "WEBP", quality=80, method=6)
                    except Exception:
                        out_rgb.save(webp_path, "WEBP", quality=80)
                return f"{base_name}-800.jpg"

            new_filename = save_image_variants_inline(form.image.data, base)
            # Remove old variants (if not placeholder)
            if product.image and product.image != "placeholder.png":
                old_base = os.path.splitext(product.image)[0]
                # if previous filenames used -{size}, strip trailing -<num>
                if '-' in old_base:
                    old_base = old_base.split('-')[0]
                for fname in os.listdir(app.config['UPLOAD_FOLDER']):
                    if fname.startswith(old_base + '-'):
                        try:
                            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], fname))
                        except:
                            pass
            product.image = new_filename

        # Обновляем дополнительные поля
        product.sku = form.sku.data or None
        product.brand = form.brand.data or None
        product.color = form.color.data or None
        product.tags = form.tags.data or ""
        # Обновляем объединённый текст поиска
        product.search_text = ' '.join(filter(None, [product.title, product.description, product.tags, product.brand, product.color, product.sku]))

        db.session.commit()
        flash(f"Товар «{product.title}» успешно обновлён!", "success")
        return redirect(url_for('admin_products'))

    return render_template("admin_edit.html", form=form, product=product)



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
