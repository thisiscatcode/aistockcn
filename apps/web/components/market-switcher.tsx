"use client";

import type { Route } from "next";
import Link from "next/link";
import { usePathname } from "next/navigation";

export function MarketSwitcher({ market }: { market: "CN" | "US" }) {
  const pathname = usePathname();
  const stage = pathname.match(/^\/(?:cn|us)\/(overview|research|quant|portfolio|execution)(?:\/|$)/)?.[1] ?? "overview";
  const remember = (nextMarket: "CN" | "US") => {
    document.cookie = `aistockcn_market=${nextMarket}; Path=/; Max-Age=31536000; SameSite=Lax`;
  };

  return (
    <div className="market-switcher" aria-label="Market">
      <Link
        href={`/us/${stage}` as Route}
        className={`market-switcher-link${market === "US" ? " is-active" : ""}`}
        aria-current={market === "US" ? "page" : undefined}
        onClick={() => remember("US")}
      >
        US Stocks
      </Link>
      <Link
        href={`/cn/${stage}` as Route}
        className={`market-switcher-link${market === "CN" ? " is-active" : ""}`}
        aria-current={market === "CN" ? "page" : undefined}
        onClick={() => remember("CN")}
      >
        CN Stocks
      </Link>
    </div>
  );
}
