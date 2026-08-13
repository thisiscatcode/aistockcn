import { ReactNode } from "react";

import { Shell } from "@/components/shell";
import type { PanelUser } from "@/lib/auth";

export function UsShell({
  user,
  title,
  subtitle,
  children
}: {
  user: PanelUser;
  title: string;
  subtitle: string;
  children: ReactNode;
}) {
  return (
    <Shell
      title={title}
      subtitle={subtitle}
      locale={user.locale}
      username={user.username}
      role={user.role}
      market="US"
    >
      {children}
    </Shell>
  );
}

export function GateChecklist({
  items
}: {
  items: Array<{ label: string; ready: boolean; detail: string }>;
}) {
  return (
    <div className="us-gate-list">
      {items.map((item) => (
        <div className={`us-gate-row ${item.ready ? "is-ready" : "is-blocked"}`} key={item.label}>
          <span aria-hidden="true">{item.ready ? "✓" : "○"}</span>
          <div>
            <strong>{item.label}</strong>
            <p>{item.detail}</p>
          </div>
        </div>
      ))}
    </div>
  );
}
