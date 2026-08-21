import type { PanelRole } from "@/lib/auth";
import type { Route } from "next";
import { ReactNode } from "react";

import { PanelLocale, getMessages } from "@/lib/i18n";
import { NavTabs } from "@/components/nav-tabs";
import { ShanghaiTime } from "@/components/shanghai-time";
import { ThemeToggle } from "@/components/theme-toggle";
import { MarketSwitcher } from "@/components/market-switcher";
import { BrandMark } from "@/components/brand-mark";

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
            <BrandMark className="aistock-brand-mark-sidebar" />
            <span><strong>AiStockCN</strong><small>Equity Intelligence</small></span>
          </div>

          <NavTabs items={navItems} />

          <div className="us-terminal-sidebar-footer">
            <div className="us-terminal-sidebar-clock">
              <ShanghaiTime
                locale={locale}
                label={market === "US" ? "New York" : "Shanghai"}
                timeZone={market === "US" ? "America/New_York" : "Asia/Shanghai"}
              />
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
            <ShanghaiTime
              locale={locale}
              label={market === "US" ? "New York" : "Shanghai"}
              timeZone={market === "US" ? "America/New_York" : "Asia/Shanghai"}
            />
          </div>
          <main className="page-content us-terminal-content">{children}</main>
        </div>
      </div>
    </div>
  );
}
