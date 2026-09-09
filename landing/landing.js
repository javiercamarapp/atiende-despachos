/* landing.js — Landing page interactions (extracted from inline <script> for CSP nonce
   compliance: script-src no admite 'unsafe-inline', ver b2b_ai/api/security_headers.py).
   Cada bloque comprueba que sus elementos existan antes de usarlos: este archivo se
   sirve para toda variante de la landing y no todas incluyen los mismos componentes. */

// ─── Scroll Reveal ───
const revealEls = document.querySelectorAll('.reveal');
if (revealEls.length && 'IntersectionObserver' in window) {
  const revealObserver = new IntersectionObserver((entries) => {
    entries.forEach(e => { if (e.isIntersecting) { e.target.classList.add('visible'); revealObserver.unobserve(e.target); } });
  }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });
  revealEls.forEach(el => revealObserver.observe(el));
}

// ─── Animated Counters ───
const counters = document.querySelectorAll('.counter');
if (counters.length && 'IntersectionObserver' in window) {
  const counterObserver = new IntersectionObserver((entries) => {
    entries.forEach(e => {
      if (e.isIntersecting) {
        const el = e.target;
        const target = parseInt(el.dataset.target, 10) || 0;
        const prefix = el.dataset.prefix || '';
        const suffix = el.dataset.suffix || '';
        let current = 0;
        const step = Math.ceil(target / 60) || 1;
        const interval = setInterval(() => {
          current += step;
          if (current >= target) { current = target; clearInterval(interval); }
          el.textContent = prefix + current.toLocaleString() + suffix;
        }, 25);
        counterObserver.unobserve(el);
      }
    });
  }, { threshold: 0.5 });
  counters.forEach(c => counterObserver.observe(c));
}

// ─── Nav Sticky ───
const nav = document.getElementById('nav');
if (nav) {
  window.addEventListener('scroll', () => {
    nav.classList.toggle('scrolled', window.scrollY > 40);
  });
}

// ─── Mobile Menu ───
const navToggle = document.getElementById('navToggle');
const mobileMenu = document.getElementById('mobileMenu');
const mobileClose = document.getElementById('mobileClose');
function closeMenu() { if (mobileMenu) mobileMenu.classList.remove('open'); }
if (navToggle && mobileMenu) {
  navToggle.addEventListener('click', () => mobileMenu.classList.add('open'));
}
if (mobileClose) {
  mobileClose.addEventListener('click', closeMenu);
}
// Close mobile menu when any menu link is clicked (CSP-safe: no inline onclick)
document.querySelectorAll('.mobile-menu-link').forEach(link => {
  link.addEventListener('click', closeMenu);
});

// ─── Accordion ───
function toggleAccordion(btn) {
  const item = btn.closest('.accordion-item');
  if (!item) return;
  const body = item.querySelector('.accordion-body');
  if (!body) return;
  const inner = body.querySelector('.accordion-body-inner');
  const isOpen = item.classList.contains('open');

  // Close all
  document.querySelectorAll('.accordion-item').forEach(i => {
    i.classList.remove('open');
    const b = i.querySelector('.accordion-body');
    if (b) b.style.maxHeight = '0';
  });

  // Toggle current
  if (!isOpen) {
    item.classList.add('open');
    body.style.maxHeight = (inner ? inner.scrollHeight : 0) + 40 + 'px';
  }
}

// Attach accordion handlers via addEventListener (CSP-safe: no inline onclick)
document.querySelectorAll('.accordion-header').forEach(btn => {
  btn.addEventListener('click', () => toggleAccordion(btn));
});

// ─── Lead form (CTA) ───
// Envía el lead al endpoint público POST /api/v1/leads (mismo origen, sin CORS).
// El backend valida nombre+email (422 si faltan) y aplica rate limit — ver
// b2b_ai/api/app.py (`create_lead`) y b2b_ai/api/rate_limiter.py (10 req/min).
function handleLeadSubmit(e) {
  e.preventDefault();
  const form = e.target;
  const data = new FormData(form);

  // Honeypot: si un bot rellenó el campo oculto "website", fingimos éxito
  // sin llamar al API (no delatamos la trampa al bot).
  if ((data.get('website') || '').trim() !== '') {
    form.reset();
    return;
  }

  const nombre = (data.get('nombre') || '').toString().trim();
  const email = (data.get('email') || '').toString().trim();
  const msgEl = document.getElementById('leadMsg');
  const btn = document.getElementById('leadSubmitBtn');

  function showMsg(text, ok) {
    if (!msgEl) return;
    msgEl.textContent = text;
    msgEl.className = 'cta-msg ' + (ok ? 'ok' : 'err');
  }

  if (!nombre || !email) {
    showMsg('Escribe tu nombre y tu email para continuar.', false);
    return;
  }

  const payload = {
    nombre: nombre,
    email: email,
    despacho: (data.get('despacho') || '').toString().trim(),
    facturas: (data.get('facturas') || '').toString().trim(),
    mensaje: (data.get('mensaje') || '').toString().trim(),
  };

  if (btn) { btn.disabled = true; btn.dataset.originalText = btn.dataset.originalText || btn.textContent; btn.textContent = 'Enviando...'; }

  fetch('/api/v1/leads', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
    .then(function (res) {
      if (res.ok) {
        showMsg('¡Gracias ' + nombre.split(' ')[0] + '! Te contactamos en menos de 24 horas.', true);
        form.reset();
      } else if (res.status === 429) {
        showMsg('Demasiados intentos. Espera un minuto e inténtalo de nuevo.', false);
      } else {
        showMsg('Ocurrió un error al enviar. Por favor inténtalo de nuevo.', false);
      }
    })
    .catch(function () {
      showMsg('Ocurrió un error al enviar. Revisa tu conexión e inténtalo de nuevo.', false);
    })
    .finally(function () {
      if (btn) { btn.disabled = false; btn.textContent = btn.dataset.originalText; }
    });
}

// Attach form handler via addEventListener (CSP-safe: no inline onsubmit)
document.addEventListener('DOMContentLoaded', function() {
  const leadForm = document.getElementById('leadForm');
  if (leadForm) {
    leadForm.addEventListener('submit', handleLeadSubmit);
  }
});
