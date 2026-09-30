
document.addEventListener('DOMContentLoaded', () => {
  // Auto-hide flash alerts after a few seconds.
  document.querySelectorAll('.alert').forEach((el) => {
    if (el.classList.contains('alert-dismissible')) return;
    setTimeout(() => {
      el.style.transition = 'opacity .3s ease';
      el.style.opacity = '0';
      setTimeout(() => el.remove(), 350);
    }, 4500);
  });

  // Add a loading state to submit buttons, except links.
  document.querySelectorAll('form').forEach(form => {
    form.addEventListener('submit', () => {
      const btn = form.querySelector('button[type="submit"]');
      if (btn && !btn.disabled) {
        btn.dataset.originalText = btn.innerHTML;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>Processing...';
        btn.disabled = true;
      }
    });
  });
});
