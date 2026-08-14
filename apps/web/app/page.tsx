import type { Metadata } from "next";

import { CustomerHomePage } from "@/components/customer-home-page";


export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "AiStockCN — AI Equity Research and Quantitative Trading",
  description: "Evidence-grounded AI research, tested quantitative signals and controlled execution for US and China equities."
};


export default async function HomePage() {
  return <CustomerHomePage />;
}
