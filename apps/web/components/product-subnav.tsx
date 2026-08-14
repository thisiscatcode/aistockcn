import type { Route } from "next";
import Link from "next/link";

export function ProductSubnav({
  items,
  active
}: {
  items: Array<{ key: string; label: string; href: Route }>;
  active: string;
}) {
  return (
    <nav className="product-subnav" aria-label="Section navigation">
      {items.map((item) => (
        <Link key={item.key} href={item.href} className={item.key === active ? "is-active" : ""} aria-current={item.key === active ? "page" : undefined}>
          {item.label}
        </Link>
      ))}
    </nav>
  );
}
