import "./globals.css";
import type { Metadata } from "next";
import { ReactNode } from "react";

import { PageRestoreCleanup } from "@/components/page-restore-cleanup";

export const metadata: Metadata = {
  title: "Aistock Quant Platform",
  description: "Public showcase and secure control panel for an end-to-end A-share quant research system."
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
