"use client";

import { useEffect } from "react";

function removeDevOverlayPortals() {
  document.querySelectorAll("nextjs-portal").forEach((portal) => portal.remove());
}

function clearBlockedPageState() {
  removeDevOverlayPortals();
  document.documentElement.removeAttribute("inert");
  document.body.removeAttribute("inert");
  document.body.style.pointerEvents = "";
  document.body.style.overflow = "";
}

export function PageRestoreCleanup() {
  useEffect(() => {
    clearBlockedPageState();

    const handlePageShow = () => clearBlockedPageState();
    const handleVisibilityChange = () => {
      if (!document.hidden) {
        clearBlockedPageState();
      }
    };

    window.addEventListener("pageshow", handlePageShow);
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      window.removeEventListener("pageshow", handlePageShow);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, []);

  return null;
}
