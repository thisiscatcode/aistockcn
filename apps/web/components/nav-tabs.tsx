"use client";

import type { Route } from "next";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { MouseEvent, useEffect, useState } from "react";

export function NavTabs({ items }: { items: Array<{ href: Route; label: string; icon?: string; status?: string }> }) {
  const pathname = usePathname();
  const [pendingLabel, setPendingLabel] = useState<string | null>(null);

  useEffect(() => {
    setPendingLabel(null);
  }, [pathname]);

  const markNavigationPending = (event: MouseEvent<HTMLAnchorElement>, active: boolean, label: string) => {
    if (
      active ||
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      return;
    }
    setPendingLabel(label);
  };

  return (
    <nav className="nav" aria-label="Primary">
      {items.map((item) => {
        const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
        return (
          <Link
            key={item.href}
            href={item.href}
            className={`nav-link ${active ? "nav-link-active" : ""}${pendingLabel === item.label ? " nav-link-pending" : ""}`}
            aria-current={active ? "page" : undefined}
            aria-busy={pendingLabel === item.label ? true : undefined}
            onClick={(event) => markNavigationPending(event, active, item.label)}
          >
            {item.icon ? <span className="nav-link-icon" aria-hidden="true">{item.icon}</span> : null}
            <span className="nav-link-label">{item.label}</span>
            {item.status ? (
              <span className={`nav-capability-dot status-${item.status}`} title={item.status.replaceAll("_", " ")} aria-label={item.status.replaceAll("_", " ")} />
            ) : null}
          </Link>
        );
      })}
      {pendingLabel ? (
        <div className="navigation-feedback" role="status" aria-live="polite">
          <span className="navigation-feedback-spinner" aria-hidden="true" />
          <span>Loading {pendingLabel}…</span>
        </div>
      ) : null}
    </nav>
  );
}
