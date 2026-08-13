import Link from "next/link";


export function AdminNavigation({ active }: { active: "platform" | "research" }) {
  return (
    <nav className="admin-navigation" aria-label="Administration">
      <Link href="/admin" className={active === "platform" ? "is-active" : undefined}>
        Platform operations
      </Link>
      <Link href="/admin/research" className={active === "research" ? "is-active" : undefined}>
        Research operations
      </Link>
    </nav>
  );
}
