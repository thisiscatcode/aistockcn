"use client";

import type { Route } from "next";
import Link from "next/link";

export function MarketSwitcher({ market }: { market: "CN" | "US" }) {
  const remember = (nextMarket: "CN" | "US") => {
    document.cookie = `aistockcn_market=${nextMarket}; Path=/; Max-Age=31536000; SameSite=Lax`;
  };

  return (
    <div className="market-switcher" aria-label="Market">
      <Link
        href={"/us/overview" as Route}
        className={`market-switcher-link${market === "US" ? " is-active" : ""}`}
        aria-current={market === "US" ? "page" : undefined}
        onClick={() => remember("US")}
      >
        US Stocks
      </Link>
      <Link
        href={"/overview" as Route}
        className={`market-switcher-link${market === "CN" ? " is-active" : ""}`}
        aria-current={market === "CN" ? "page" : undefined}
        onClick={() => remember("CN")}
      >
        A-Shares
      </Link>
    </div>
  );
}
