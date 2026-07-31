const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const revealNodes = $$('.reveal');
if (reducedMotion || !('IntersectionObserver' in window)) {
  revealNodes.forEach((node) => node.classList.add('visible'));
} else {
  const revealObserver = new IntersectionObserver((entries, observer) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      entry.target.classList.add('visible');
      observer.unobserve(entry.target);
    }
  }, { threshold: 0.12, rootMargin: '0px 0px -5% 0px' });
  revealNodes.forEach((node) => revealObserver.observe(node));
}

const navigationLinks = $$('.site-header nav a');
const sectionById = new Map(
  navigationLinks
    .map((link) => [link.getAttribute('href')?.slice(1), link])
    .filter(([id]) => Boolean(id))
);

if ('IntersectionObserver' in window) {
  const sectionObserver = new IntersectionObserver((entries) => {
    const visible = entries
      .filter((entry) => entry.isIntersecting)
      .sort((left, right) => right.intersectionRatio - left.intersectionRatio)[0];

    if (!visible) return;
    navigationLinks.forEach((link) => link.classList.remove('active'));
    sectionById.get(visible.target.id)?.classList.add('active');
  }, { threshold: [0.2, 0.45, 0.7], rootMargin: '-20% 0px -55% 0px' });

  sectionById.forEach((_, id) => {
    const section = document.getElementById(id);
    if (section) sectionObserver.observe(section);
  });
}

const dialog = $('#image-dialog');
const dialogImage = $('#dialog-image');
const dialogTitle = $('#dialog-title');
const dialogClose = $('#dialog-close');
let previousFocus = null;

function openCapture(button) {
  const image = button.dataset.image;
  const title = button.dataset.title || 'MAYA interface capture';
  if (!image) return;

  if (!dialog || typeof dialog.showModal !== 'function') {
    window.location.assign(image);
    return;
  }

  previousFocus = document.activeElement;
  dialogImage.src = image;
  dialogImage.alt = title;
  dialogTitle.textContent = title;
  dialog.showModal();
  dialogClose?.focus();
}

function closeCapture() {
  if (!dialog?.open) return;
  dialog.close();
  dialogImage.removeAttribute('src');
  if (previousFocus instanceof HTMLElement) previousFocus.focus();
}

$$('.capture').forEach((button) => {
  button.addEventListener('click', () => openCapture(button));
});

dialogClose?.addEventListener('click', closeCapture);
dialog?.addEventListener('click', (event) => {
  if (event.target === dialog) closeCapture();
});
dialog?.addEventListener('cancel', (event) => {
  event.preventDefault();
  closeCapture();
});

$$('img').forEach((image) => {
  image.addEventListener('error', () => {
    image.closest('.capture, figure')?.classList.add('image-error');
    image.alt = `${image.alt || 'Interface capture'} — artifact unavailable`;
  });
});

const header = $('.site-header');
let ticking = false;
function updateHeaderState() {
  header?.classList.toggle('scrolled', window.scrollY > 20);
  ticking = false;
}
window.addEventListener('scroll', () => {
  if (ticking) return;
  ticking = true;
  window.requestAnimationFrame(updateHeaderState);
}, { passive: true });
updateHeaderState();
