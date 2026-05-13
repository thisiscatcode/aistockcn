import type { PanelRole } from "@/lib/auth";
import type { Route } from "next";
import { ReactNode } from "react";

import { PanelLocale, getMessages } from "@/lib/i18n";
import { NavTabs } from "@/components/nav-tabs";
import { ShanghaiTime } from "@/components/shanghai-time";

function localeTag(locale: PanelLocale) {
  return locale === "zh-Hant" ? "zh-Hant-HK" : "en-US";
}

export function Shell({
  title,
  subtitle,
  children,
  locale,
  username,
  role
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
  locale: PanelLocale;
  username: string;
  role: PanelRole;
}) {
  const copy = getMessages(locale);
  const shanghaiTimeNow = new Intl.DateTimeFormat(localeTag(locale), {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZone: "Asia/Shanghai",
    timeZoneName: "short"
  }).format(new Date());
  const navItem = (href: Route, label: string) => ({ href, label });
  const navItems: Array<{ href: Route; label: string }> = [
    navItem("/overview", copy.shell.nav.overview),
    navItem("/batch", copy.shell.nav.batch),
    navItem("/data", copy.shell.nav.data),
    navItem("/models", copy.shell.nav.models),
    navItem("/picks", copy.shell.nav.picks),
    navItem("/paper", copy.shell.nav.paper),
    ...(role === "admin" ? [navItem("/admin", copy.shell.nav.admin)] : [])
  ];

  return (
    <div className="shell">
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
            <ShanghaiTime locale={locale} label={copy.shell.shanghaiTime} initialValue={shanghaiTimeNow} />
          </div>
        </div>
      </header>
      <main className="page-content">{children}</main>
    </div>
  );
}
