import Image from "next/image";

export function BrandMark({ className = "" }: { className?: string }) {
  return (
    <span className={`aistock-brand-mark${className ? ` ${className}` : ""}`} aria-hidden="true">
      <Image src="/brand/aistockcn-mark.png" alt="" width={512} height={512} />
    </span>
  );
}

export function BrandWordmark({ className = "" }: { className?: string }) {
  return (
    <span className={`aistock-brand-wordmark${className ? ` ${className}` : ""}`} aria-hidden="true">
      <Image src="/brand/aistockcn-wordmark.png" alt="" width={1200} height={300} priority />
    </span>
  );
}

export function BrandLockup({ className = "" }: { className?: string }) {
  return (
    <span className={`aistock-brand-lockup${className ? ` ${className}` : ""}`} aria-hidden="true">
      <Image src="/brand/aistockcn-lockup.png" alt="" width={1600} height={430} priority />
    </span>
  );
}
