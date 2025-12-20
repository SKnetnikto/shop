document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.quantity-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const form = btn.closest('.quantity-form');
            const input = form.querySelector('.quantity-input');
            let value = parseInt(input.value) || 1;

            if (btn.classList.contains('minus')) {
                value = Math.max(1, value - 1);
            } else {
                value += 1;
            }

            input.value = value;
            form.submit();
        });
    });
});