import type { PanelRole } from "@/lib/auth";
import type { Route } from "next";
import { ReactNode } from "react";

import { PanelLocale, getMessages } from "@/lib/i18n";
import { NavTabs } from "@/components/nav-tabs";
import { ThemeToggle } from "@/components/theme-toggle";
import { MarketSwitcher } from "@/components/market-switcher";
import { BrandSidebarLockup } from "@/components/brand-mark";
import { MarketSessionClock } from "@/components/market-session-clock";
import { getUsMarketSession } from "@/lib/api";
import { getCnMarketSession } from "@/lib/cn-market-session";

export async function Shell({
  title,
  subtitle,
  children,
  locale,
  username,
  role,
  market = "CN",
  tone = "light",
  compact = false
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
  locale: PanelLocale;
  username: string;
  role: PanelRole;
  market?: "CN" | "US";
  tone?: "light" | "dark";
  compact?: boolean;
}) {
  const copy = getMessages(locale);
  const marketSession = market === "US"
    ? await getUsMarketSession().catch(() => null)
    : getCnMarketSession();
  const marketSessionEndpoint = market === "US" ? "/api/us/session" : "/api/cn/session";
  void title;
  void subtitle;
  void tone;
  void compact;
  const navItem = (href: Route, label: string, icon?: string) => ({
    href,
    label,
    icon
  });
  const root = market === "US" ? "/us" : "/cn";
  const businessNavItems: Array<{ href: Route; label: string; icon?: string }> = [
    navItem(`${root}/overview` as Route, "Overview", "◫"),
    navItem(`${root}/research` as Route, "Research", "✦"),
    navItem(`${root}/quant` as Route, "Quant", "⌁"),
    navItem(`${root}/portfolio` as Route, "Portfolio", "◆"),
    navItem(`${root}/execution` as Route, "Execution", "⇄")
  ];
  const navItems = role === "admin"
    ? [...businessNavItems, navItem("/admin", copy.shell.nav.admin, "⚙")]
    : businessNavItems;

  return (
    <div className="theme-shell-root us-terminal-root" data-theme-root data-theme="bright">
      <div className="us-terminal-shell">
        <aside className="us-terminal-sidebar">
          <div className="us-terminal-brand">
            <BrandSidebarLockup />
          </div>

          <NavTabs items={navItems} />

          <div className="us-terminal-sidebar-footer">
            <div className="us-terminal-sidebar-clock">
              <MarketSessionClock initialSession={marketSession} refreshEndpoint={marketSessionEndpoint} />
            </div>
            <MarketSwitcher market={market} />
            <div className="us-terminal-user">
              <span className="us-terminal-avatar" aria-hidden="true">{username.slice(0, 1).toUpperCase()}</span>
              <span><small>Signed in</small><strong>{username}</strong></span>
              <ThemeToggle />
            </div>
            <form action="/auth/logout" method="post" className="hero-logout-form">
              <button type="submit" className="logout-button">{copy.shell.logout}</button>
            </form>
          </div>
        </aside>

        <div className="us-terminal-workspace">
          <div className="us-terminal-mobile-clock">
            <MarketSessionClock initialSession={marketSession} refreshEndpoint={marketSessionEndpoint} />
          </div>
          <main className="page-content us-terminal-content">{children}</main>
        </div>
      </div>
    </div>
  );
}
