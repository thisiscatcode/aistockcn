"use client";

import type { Route } from "next";
import Link from "next/link";
import { usePathname } from "next/navigation";

export function NavTabs({ items }: { items: Array<{ href: Route; label: string }> }) {
  const pathname = usePathname();

  return (
    <nav className="nav" aria-label="Primary">
      {items.map((item) => {
        const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
        return (
          <Link key={item.href} href={item.href} className={`nav-link ${active ? "nav-link-active" : ""}`}>
            <span className="nav-link-label">{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
