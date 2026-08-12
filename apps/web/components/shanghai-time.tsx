"use client";

import { useEffect, useState } from "react";

import type { PanelLocale } from "@/lib/i18n";

const SHANGHAI_TIME_ZONE = "Asia/Shanghai";

function localeTag(locale: PanelLocale) {
  return locale === "zh-Hant" ? "zh-Hant-HK" : "en-US";
}

function formatMarketTime(value: Date, locale: PanelLocale, timeZone: string) {
  return new Intl.DateTimeFormat(localeTag(locale), {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZone,
    timeZoneName: "short"
  }).format(value);
}

export function ShanghaiTime({
  locale,
  label,
  timeZone = SHANGHAI_TIME_ZONE
}: {
  locale: PanelLocale;
  label: string;
  timeZone?: string;
}) {
  const [value, setValue] = useState("—");

  useEffect(() => {
    const updateValue = () => setValue(formatMarketTime(new Date(), locale, timeZone));
    updateValue();
    const timerId = window.setInterval(updateValue, 1000);
    return () => window.clearInterval(timerId);
  }, [locale, timeZone]);

  return (
    <span className="shell-time">
      <span className="shell-time-label">{label}:</span>{" "}
      <time className="shell-time-value">{value}</time>
    </span>
  );
}
