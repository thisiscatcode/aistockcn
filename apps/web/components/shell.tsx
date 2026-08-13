import type { PanelRole } from "@/lib/auth";
import type { Route } from "next";
import { ReactNode } from "react";

import { PanelLocale, getMessages } from "@/lib/i18n";
import { NavTabs } from "@/components/nav-tabs";
import { ShanghaiTime } from "@/components/shanghai-time";
import { ThemeToggle } from "@/components/theme-toggle";
import { MarketSwitcher } from "@/components/market-switcher";

export function Shell({
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
  const isDark = tone === "dark";
  const navItem = (href: Route, label: string, icon?: string) => ({ href, label, icon });
  const businessNavItems: Array<{ href: Route; label: string; icon?: string }> = market === "US"
    ? [
        navItem("/us/overview" as Route, copy.shell.nav.overview, "◫"),
        navItem("/research" as Route, copy.shell.nav.research, "✦"),
        navItem("/us/data" as Route, copy.shell.nav.data, "⌕"),
        navItem("/us/picks" as Route, copy.shell.nav.picks, "◆"),
        navItem("/us/paper" as Route, copy.shell.nav.paper, "$")
      ]
    : [
        navItem("/overview", copy.shell.nav.overview),
        navItem("/research" as Route, copy.shell.nav.research),
        navItem("/data", copy.shell.nav.data),
        navItem("/picks", copy.shell.nav.picks),
        navItem("/paper", copy.shell.nav.paper)
      ];
  const navItems = role === "admin"
    ? market === "US"
      ? [
          ...businessNavItems,
          navItem("/us/system-monitor" as Route, "System", "●"),
          navItem("/us/batch" as Route, "Data Jobs", "↻"),
          navItem("/us/models" as Route, "Models", "◇"),
          navItem("/admin", copy.shell.nav.admin, "⚙")
        ]
      : [...businessNavItems, navItem("/admin", copy.shell.nav.admin)]
    : businessNavItems;

  if (market === "US") {
    return (
      <div className="theme-shell-root us-terminal-root" data-theme-root data-theme="bright">
        <div className="us-terminal-shell">
          <aside className="us-terminal-sidebar">
            <div className="us-terminal-brand">
              <span className="us-terminal-mark" aria-hidden="true">A</span>
              <span><strong>AiStockCN</strong><small>US Intelligence</small></span>
            </div>

            <div className="us-terminal-nav-label">Workspace</div>
            <NavTabs items={navItems} />

            <div className="us-terminal-sidebar-footer">
              <div className="us-terminal-sidebar-clock">
                <ShanghaiTime locale={locale} label="New York" timeZone="America/New_York" />
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
              <ShanghaiTime locale={locale} label="New York" timeZone="America/New_York" />
            </div>
            <main className="page-content us-terminal-content">{children}</main>
          </div>
        </div>
      </div>
    );
  }

  const content = (
    <div className={`shell${isDark ? " shell-dark" : ""}${compact ? " shell-compact" : ""}`}>
      <header className="hero">
        <div className="hero-topline">
          <div className="hero-copy">
            <p className="eyebrow brand-status-line">
              <span className="live-indicator" aria-label="Live status">
                <span className="live-dot" aria-hidden="true">●</span>
                <span>LIVE</span>
              </span>
              <span>{copy.brand}</span>
            </p>
            <h1>{title}</h1>
            {subtitle ? <p className="hero-subtitle">{subtitle}</p> : null}
          </div>
          <div className="hero-meta" aria-label={copy.shell.signedInAs}>
            <div className="hero-meta-line">
              <MarketSwitcher market={market} />
              <ThemeToggle />
              <span>{copy.shell.signedInAs}:</span> <strong>{username}</strong>
              <form action="/auth/logout" method="post" className="hero-logout-form">
                <button type="submit" className="logout-button">
                  {copy.shell.logout}
                </button>
              </form>
            </div>
          </div>
        </div>
        <div className="nav-row">
          <NavTabs items={navItems} />
          <div className="nav-time">
            <ShanghaiTime
              locale={locale}
              label={copy.shell.shanghaiTime}
              timeZone="Asia/Shanghai"
            />
          </div>
        </div>
      </header>
      <main className="page-content">{children}</main>
    </div>
  );

  return (
    <div className={`theme-shell-root${isDark ? " page-dark" : ""}`} data-theme-root data-theme={isDark ? "dark" : "bright"}>
      {content}
    </div>
  );
}
