import type { Route } from "next";
import type { PanelRole } from "@/lib/auth";

export type QuantNavItem = {
  key: string;
  label: string;
  href: Route;
};

export function quantNavigation(market: "CN" | "US", role?: PanelRole): QuantNavItem[] {
  const root = market === "US" ? "/us/quant" : "/cn/quant";
  const shared: QuantNavItem[] = [
    { key: "signals", label: "Signals", href: `${root}?view=signals` as Route },
    { key: "methodology", label: "Methodology", href: `${root}?view=methodology` as Route },
    { key: "walk-forward", label: "Walk-forward", href: `${root}?view=walk-forward` as Route },
    { key: "explorer", label: "Explorer", href: `${root}?view=explorer` as Route }
  ];

  if (market === "CN") {
    return [
      { key: "performance", label: "Performance", href: "/cn/quant" as Route },
      shared[0],
      ...(role === "admin"
        ? [{ key: "models", label: "Models & Backtests", href: "/cn/quant?view=models" as Route }]
        : []),
      ...shared.slice(1)
    ];
  }

  return shared;
}
