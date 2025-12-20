document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.quantity-form').forEach(form => {
        const buttons = form.querySelectorAll('.quantity-btn');
        const input = form.querySelector('.quantity-input');

        buttons.forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();

                if (form.dataset.submitting === 'true') return;

                let value = parseInt(input.value, 10);
                if (isNaN(value)) value = 1;

                if (btn.classList.contains('minus')) {
                    if (value <= 1) {
                        // Удаляем товар: устанавливаем 0 и отправляем
                        input.value = 0;
                    } else {
                        input.value = value - 1;
                    }
                } else {
                    input.value = value + 1;
                }

                // Блокировка и отправка
                form.dataset.submitting = 'true';
                buttons.forEach(b => b.disabled = true);
                btn.textContent = '...';

                form.submit();
            });
        });
    });
});

window.addEventListener('pageshow', () => {
    document.querySelectorAll('.quantity-form').forEach(form => {
        delete form.dataset.submitting;
        form.querySelectorAll('.quantity-btn').forEach(b => {
            b.disabled = false;
            if (b.classList.contains('plus')) b.textContent = '+';
            if (b.classList.contains('minus')) b.textContent = '-';
        });
    });
});