import "./globals.css";
import "./us-terminal.css";
import type { Metadata } from "next";
import { ReactNode } from "react";

import { PageRestoreCleanup } from "@/components/page-restore-cleanup";

export const metadata: Metadata = {
  title: "AiStockCN",
  description: "AI-powered equity research and quantitative trading for US and China markets."
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
