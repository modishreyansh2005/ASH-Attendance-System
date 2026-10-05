// Ash Education Smart Attendance - Global UI Scripts
(function () {
  const STORAGE_KEY = 'ash_sidebar_collapsed';

  // Apply saved collapsed state before full DOM render to avoid flash of expanded sidebar
  try {
    const isCollapsed = localStorage.getItem(STORAGE_KEY) === 'true';
    if (isCollapsed && window.innerWidth > 992) {
      document.documentElement.classList.add('sidebar-collapsed');
    }
  } catch (e) {
    console.warn("Storage access restricted:", e);
  }

  document.addEventListener('DOMContentLoaded', () => {
    // 1. Auto dismiss flash messages after 5 seconds
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
      setTimeout(() => {
        alert.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
        alert.style.opacity = '0';
        alert.style.transform = 'translateY(-10px)';
        setTimeout(() => alert.remove(), 500);
      }, 5000);
    });

    // 2. Single Navigation Bar Toggle Controller
    const toggleBtn = document.getElementById('sidebar-toggle-btn');
    const closeBtn = document.getElementById('sidebar-close-btn');
    const backdrop = document.getElementById('sidebar-backdrop');
    const navLinks = document.querySelectorAll('.sidebar-nav .nav-link');

    function toggleSidebar() {
      const isMobile = window.innerWidth <= 992;
      if (isMobile) {
        // Mobile off-canvas drawer
        const isOpen = document.body.classList.toggle('sidebar-mobile-open');
        if (backdrop) backdrop.classList.toggle('active', isOpen);
      } else {
        // Desktop compact / icon-only collapse mode
        const collapsed = document.documentElement.classList.toggle('sidebar-collapsed');
        try {
          localStorage.setItem(STORAGE_KEY, collapsed ? 'true' : 'false');
        } catch (e) {}
        updateToggleTitle();
      }
    }

    function closeMobileSidebar() {
      document.body.classList.remove('sidebar-mobile-open');
      if (backdrop) backdrop.classList.remove('active');
    }

    function updateToggleTitle() {
      if (!toggleBtn) return;
      const isCollapsed = document.documentElement.classList.contains('sidebar-collapsed');
      toggleBtn.setAttribute('title', isCollapsed ? 'Show / Expand Navigation Bar (Ctrl+B)' : 'Hide / Collapse Navigation Bar (Ctrl+B)');
    }

    if (toggleBtn) {
      toggleBtn.addEventListener('click', (e) => {
        e.preventDefault();
        toggleSidebar();
      });
    }

    if (closeBtn) {
      closeBtn.addEventListener('click', (e) => {
        e.preventDefault();
        closeMobileSidebar();
      });
    }

    if (backdrop) {
      backdrop.addEventListener('click', closeMobileSidebar);
    }

    // Auto-close mobile drawer on clicking any navigation link
    navLinks.forEach(link => {
      link.addEventListener('click', () => {
        if (window.innerWidth <= 992) {
          closeMobileSidebar();
        }
      });
    });

    // Keyboard shortcut: Ctrl+B or Cmd+B to toggle sidebar navigation
    document.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b') {
        e.preventDefault();
        toggleSidebar();
      } else if (e.key === 'Escape' && document.body.classList.contains('sidebar-mobile-open')) {
        closeMobileSidebar();
      }
    });

    // Responsive resize handler
    window.addEventListener('resize', () => {
      if (window.innerWidth > 992) {
        closeMobileSidebar();
        try {
          if (localStorage.getItem(STORAGE_KEY) === 'true') {
            document.documentElement.classList.add('sidebar-collapsed');
          }
        } catch (e) {}
      } else {
        document.documentElement.classList.remove('sidebar-collapsed');
      }
    });

    updateToggleTitle();
  });
})();
