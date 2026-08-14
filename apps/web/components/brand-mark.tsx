export function BrandMark({ className = "" }: { className?: string }) {
  return (
    <span className={`aistock-brand-mark${className ? ` ${className}` : ""}`} aria-hidden="true">
      <svg viewBox="0 0 40 40" role="presentation" focusable="false">
        <path className="brand-candle brand-candle-left" d="M10 13v13M7.5 17h5v6h-5z" />
        <path className="brand-candle brand-candle-mid" d="M19 10v17M16.5 14h5v8h-5z" />
        <path className="brand-candle brand-candle-right" d="M28 7v18M25.5 11h5v8h-5z" />
        <path className="brand-trend" d="M8 29l7-7 5 3 11-13" />
        <circle className="brand-market brand-market-us" cx="8" cy="29" r="2" />
        <circle className="brand-market brand-market-cn" cx="31" cy="12" r="2.4" />
      </svg>
    </span>
  );
}
