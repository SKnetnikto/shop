// static/js/main.js — управление бургером и выпадашкой на мобилке
document.addEventListener("DOMContentLoaded", () => {
    const burger = document.querySelector(".burger");
    const nav = document.querySelector(".nav");
    const dropdowns = document.querySelectorAll(".dropdown");

    // Бургер
    burger.addEventListener("click", () => {
        burger.classList.toggle("active");
        nav.classList.toggle("active");
    });

    // Выпадашка "Товары" на мобильных
    dropdowns.forEach(d => {
        const link = d.querySelector("a");
        link.addEventListener("click", (e) => {
            if (window.innerWidth <= 992) {
                e.preventDefault();
                d.classList.toggle("active");
            }
        });
    });

    // Закрытие при ресайзе
    window.addEventListener("resize", () => {
        if (window.innerWidth > 992) {
            nav.classList.remove("active");
            burger.classList.remove("active");
        }
    });
});