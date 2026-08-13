import type { Metadata } from "next";

import { CustomerHomePage } from "@/components/customer-home-page";


export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "AiStockCN — Systematic Equity Research Platform",
  description: "Live market data, quantitative research, model signals and source-grounded company research."
};


export default async function HomePage() {
  return <CustomerHomePage />;
}
