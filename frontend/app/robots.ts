import type { MetadataRoute } from "next";

import { getPublicSiteUrl } from "@/lib/api";

export default function robots(): MetadataRoute.Robots {
  const siteUrl = getPublicSiteUrl();
  return {
    rules: {
      userAgent: "*",
      allow: "/",
    },
    sitemap: `${siteUrl}/sitemap.xml`,
  };
}
