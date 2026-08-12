import "./globals.css";
import type { Metadata } from "next";
import { ReactNode } from "react";

import { PageRestoreCleanup } from "@/components/page-restore-cleanup";

export const metadata: Metadata = {
  title: "AiStockCN Research Copilot",
  description: "Evidence-grounded research across live US equity data, deterministic calculations and model inference."
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <PageRestoreCleanup />
        {children}
      </body>
    </html>
  );
}
