// бургер + тёмная тема + превью
document.addEventListener("DOMContentLoaded", () => {
    // === Бургер ===
    const burger = document.querySelector(".burger");
    const nav = document.querySelector(".nav");

    if (burger && nav) {
        burger.addEventListener("click", () => {
            burger.classList.toggle("active");
            nav.classList.toggle("active");
        });
    }

    // === темная тема ===
    const themeSwitch = document.getElementById("theme-switch");
    const body = document.body;

    // загрузка темной темы 
    if (localStorage.getItem("theme") === "dark") {
        body.classList.add("dark-mode");
        themeSwitch.checked = true;
    }

    themeSwitch?.addEventListener("change", () => {
        if (themeSwitch.checked) {
            body.classList.add("dark-mode");
            localStorage.setItem("theme", "dark");
        } else {
            body.classList.remove("dark-mode");
            localStorage.setItem("theme", "light");
        }
    });

    // === ПРЕВЬЮ ФОТО ===
    const input = document.querySelector('input[type="file"]');
    const preview = document.getElementById('image-preview');
    const img = document.getElementById('preview-img');

    if (input && preview && img) {
        input.addEventListener('change', function (e) {
            const file = e.target.files[0];
            if (file) {
                const reader = new FileReader();
                reader.onload = function (e) {
                    img.src = e.target.result;
                    preview.style.display = 'block';
                }
                reader.readAsDataURL(file);
            }
        });
    }
});