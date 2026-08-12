"use client";

import { useEffect, useState } from "react";

type ThemeMode = "dark" | "bright";

const STORAGE_KEY = "aistockcn-panel-theme";

function applyTheme(theme: ThemeMode) {
  const roots = document.querySelectorAll<HTMLElement>("[data-theme-root]");
  roots.forEach((root) => {
    const shell = root.querySelector<HTMLElement>(".shell");
    const dark = theme === "dark";
    root.classList.toggle("page-dark", dark);
    root.dataset.theme = theme;
    shell?.classList.toggle("shell-dark", dark);
  });
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<ThemeMode>("bright");

  useEffect(() => {
    const savedTheme = window.localStorage.getItem(STORAGE_KEY);
    const nextTheme: ThemeMode = savedTheme === "dark" ? "dark" : "bright";
    setTheme(nextTheme);
    applyTheme(nextTheme);
  }, []);

  function toggleTheme() {
    const nextTheme: ThemeMode = theme === "dark" ? "bright" : "dark";
    setTheme(nextTheme);
    window.localStorage.setItem(STORAGE_KEY, nextTheme);
    applyTheme(nextTheme);
  }

  const switchingTo = theme === "dark" ? "bright" : "dark";
  const switchingToLabel = switchingTo === "bright" ? "light" : "dark";

  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={toggleTheme}
      aria-label={`Switch to ${switchingToLabel} theme`}
      title={`Switch to ${switchingToLabel} theme`}
    >
      <span className={`theme-toggle-icon theme-toggle-${switchingTo}`} aria-hidden="true" />
    </button>
  );
}
