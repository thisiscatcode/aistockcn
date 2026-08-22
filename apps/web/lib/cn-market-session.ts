import type { MarketSession } from "@/lib/api";

const CN_TIME_ZONE = "Asia/Shanghai";
const MORNING_OPEN_MINUTE = 9 * 60 + 30;
const MORNING_CLOSE_MINUTE = 11 * 60 + 30;
const AFTERNOON_OPEN_MINUTE = 13 * 60;
const AFTERNOON_CLOSE_MINUTE = 15 * 60;

type ShanghaiDateParts = {
  year: number;
  month: number;
  day: number;
  weekday: number;
  minuteOfDay: number;
};

function shanghaiDateParts(value: Date): ShanghaiDateParts {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: CN_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).formatToParts(value);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  const year = Number(values.year);
  const month = Number(values.month);
  const day = Number(values.day);
  const hour = Number(values.hour) % 24;
  const minute = Number(values.minute);
  const weekday = new Date(Date.UTC(year, month - 1, day)).getUTCDay();
  return { year, month, day, weekday, minuteOfDay: hour * 60 + minute };
}

function shanghaiTimestamp(parts: ShanghaiDateParts, dayOffset: number, minuteOfDay: number) {
  const hour = Math.floor(minuteOfDay / 60);
  const minute = minuteOfDay % 60;
  return new Date(Date.UTC(parts.year, parts.month - 1, parts.day + dayOffset, hour - 8, minute));
}

function isWeekday(weekday: number) {
  return weekday >= 1 && weekday <= 5;
}

function nextWeekdayOpen(parts: ShanghaiDateParts) {
  for (let offset = 1; offset <= 7; offset += 1) {
    const weekday = new Date(Date.UTC(parts.year, parts.month - 1, parts.day + offset)).getUTCDay();
    if (isWeekday(weekday)) return shanghaiTimestamp(parts, offset, MORNING_OPEN_MINUTE);
  }
  return null;
}

export function getCnMarketSession(now = new Date()): MarketSession {
  const parts = shanghaiDateParts(now);
  const isTradingWeekday = isWeekday(parts.weekday);
  let status: MarketSession["status"] = "closed";
  let nextTransition: MarketSession["next_transition"] = "opens";
  let nextTransitionAt: Date | null = null;

  if (isTradingWeekday && parts.minuteOfDay < MORNING_OPEN_MINUTE) {
    nextTransitionAt = shanghaiTimestamp(parts, 0, MORNING_OPEN_MINUTE);
  } else if (
    isTradingWeekday &&
    parts.minuteOfDay >= MORNING_OPEN_MINUTE &&
    parts.minuteOfDay < MORNING_CLOSE_MINUTE
  ) {
    status = "open";
    nextTransition = "closes";
    nextTransitionAt = shanghaiTimestamp(parts, 0, MORNING_CLOSE_MINUTE);
  } else if (isTradingWeekday && parts.minuteOfDay < AFTERNOON_OPEN_MINUTE) {
    nextTransitionAt = shanghaiTimestamp(parts, 0, AFTERNOON_OPEN_MINUTE);
  } else if (
    isTradingWeekday &&
    parts.minuteOfDay >= AFTERNOON_OPEN_MINUTE &&
    parts.minuteOfDay < AFTERNOON_CLOSE_MINUTE
  ) {
    status = "open";
    nextTransition = "closes";
    nextTransitionAt = shanghaiTimestamp(parts, 0, AFTERNOON_CLOSE_MINUTE);
  } else {
    nextTransitionAt = nextWeekdayOpen(parts);
  }

  return {
    market: "CN",
    status,
    label: `CN Market ${status === "open" ? "Open" : "Closed"}`,
    timezone: CN_TIME_ZONE,
    timezone_abbreviation: "GMT+8",
    observed_at: now.toISOString(),
    next_transition: nextTransitionAt ? nextTransition : null,
    next_transition_at: nextTransitionAt?.toISOString() ?? null
  };
}
