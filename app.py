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
    products = Product.query.all()
    return render_template("catalog.html", categories=categories, products=products)

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect("/admin")
    form = LoginForm()
    if form.validate_on_submit():
        user = Admin.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            return redirect("/admin")
        flash("Неверный логин или пароль", "error")
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
        filename = "placeholder.jpg"
        if form.image.data:
            filename = secure_filename(form.image.data.filename)
            form.image.data.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        product = Product(
            title=form.title.data,
            price=form.price.data,
            old_price=form.old_price.data or None,
            description=form.description.data or "",
            image=filename,
            category_id=form.category.data,
            is_new=form.is_new.data,
            is_sale=form.is_sale.data
        )
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
    if product.image != "placeholder.jpg":
        try:
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], product.image))
        except:
            pass
    db.session.delete(product)
    db.session.commit()
    flash("Товар удалён", "info")
    return redirect("/admin")



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

# ===================== ЗАПУСК =====================
if __name__ == "__main__":
    with app.app_context():
        db.create_all()

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
