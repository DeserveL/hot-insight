import type { Metadata } from "next";
import type { ReactNode } from "react";

import { SiteHeader } from "@/components/site-header";
import { getPublicSiteUrl } from "@/lib/api";

import "./globals.css";

const siteUrl = getPublicSiteUrl();

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: {
    default: "热点洞察",
    template: "%s | 热点洞察",
  },
  description: "追踪微博热搜，整理事实脉络与 AI 辅助洞察。",
  icons: {
    icon: "/favicon.ico",
    apple: "/apple-touch-icon.png",
  },
  openGraph: {
    title: "热点洞察",
    description: "追踪微博热搜，整理事实脉络与 AI 辅助洞察。",
    url: siteUrl,
    siteName: "热点洞察",
    locale: "zh_CN",
    type: "website",
  },
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <SiteHeader />
        {children}
      </body>
    </html>
  );
}
