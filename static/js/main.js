// ===== BUSCAPIEZA RD — MAIN JS =====

// Hamburger menu
const hamburger   = document.getElementById('hamburger');
const mobileMenu  = document.getElementById('mobileMenu');
if (hamburger) {
  hamburger.addEventListener('click', () => {
    mobileMenu.classList.toggle('open');
  });
}

// Auto-dismiss flash messages
document.querySelectorAll('.flash').forEach(f => {
  setTimeout(() => { f.style.opacity='0'; setTimeout(()=>f.remove(),300); }, 5000);
});

// ===== PWA: Registro del Service Worker + aviso de actualización =====
function showUpdateToast(reg) {
  const toast = document.getElementById('pwaUpdateToast');
  if (!toast) return;
  toast.hidden = false;

  document.getElementById('pwaUpdateBtn').onclick = () => {
    if (reg.waiting) reg.waiting.postMessage('SKIP_WAITING');
    toast.hidden = true;
  };
  document.getElementById('pwaUpdateClose').onclick = () => { toast.hidden = true; };
}

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').then(reg => {
      if (reg.waiting && navigator.serviceWorker.controller) showUpdateToast(reg);

      reg.addEventListener('updatefound', () => {
        const fresh = reg.installing;
        if (!fresh) return;
        fresh.addEventListener('statechange', () => {
          if (fresh.state === 'installed' && navigator.serviceWorker.controller) {
            showUpdateToast(reg);
          }
        });
      });
    }).catch(err => console.log('SW error:', err));
  });

  let refreshing = false;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (refreshing) return;
    refreshing = true;
    window.location.reload();
  });
}

// ===== PWA: Prompt de instalación (Android / Escritorio) =====
const isStandalone = window.matchMedia('(display-mode: standalone)').matches
  || window.navigator.standalone === true;

let deferredInstallPrompt = null;
const installBanner = document.getElementById('pwaInstallBanner');

window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredInstallPrompt = e;
  if (isStandalone || !installBanner) return;
  const dismissedUntil = Number(localStorage.getItem('bp_install_dismissed_until') || 0);
  if (Date.now() < dismissedUntil) return;
  installBanner.hidden = false;
});

document.getElementById('pwaInstallBtn')?.addEventListener('click', async () => {
  if (!deferredInstallPrompt) return;
  installBanner.hidden = true;
  deferredInstallPrompt.prompt();
  await deferredInstallPrompt.userChoice;
  deferredInstallPrompt = null;
});

document.getElementById('pwaInstallClose')?.addEventListener('click', () => {
  installBanner.hidden = true;
  localStorage.setItem('bp_install_dismissed_until', String(Date.now() + 14 * 24 * 60 * 60 * 1000));
});

window.addEventListener('appinstalled', () => {
  if (installBanner) installBanner.hidden = true;
  deferredInstallPrompt = null;
});

// ===== PWA: instrucciones manuales para iOS (sin beforeinstallprompt) =====
(function iosInstallHint() {
  const isIos = /iphone|ipad|ipod/i.test(window.navigator.userAgent);
  const iosBanner = document.getElementById('pwaIosBanner');
  if (!isIos || isStandalone || !iosBanner) return;

  const dismissedUntil = Number(localStorage.getItem('bp_ios_dismissed_until') || 0);
  if (Date.now() < dismissedUntil) return;

  iosBanner.hidden = false;
  document.getElementById('pwaIosClose')?.addEventListener('click', () => {
    iosBanner.hidden = true;
    localStorage.setItem('bp_ios_dismissed_until', String(Date.now() + 14 * 24 * 60 * 60 * 1000));
  });
})();
