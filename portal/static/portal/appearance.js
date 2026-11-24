(() => {
  const storageKey = "portal.appearance.colorMode";
  const systemTheme = window.matchMedia("(prefers-color-scheme: dark)");
  const appearance = document.documentElement.dataset;

  try {
    const saved = localStorage.getItem(storageKey);
    if (saved === "light" || saved === "dark") appearance.colorMode = saved;
  } catch {
    // With storage disabled, start with the system theme.
  }

  function isDark() {
    return appearance.colorMode ? appearance.colorMode === "dark" : systemTheme.matches;
  }

  document.addEventListener("DOMContentLoaded", () => {
    const toggle = document.querySelector("[data-theme-toggle]");

    function updateToggle() {
      toggle.setAttribute("aria-checked", String(isDark()));
    }

    toggle.addEventListener("click", () => {
      appearance.colorMode = isDark() ? "light" : "dark";
      updateToggle();
      try {
        localStorage.setItem(storageKey, appearance.colorMode);
      } catch {
        // Keep the new theme active on this page.
      }
    });
    systemTheme.addEventListener("change", updateToggle);
    updateToggle();
    toggle.hidden = false;
  });
})();
