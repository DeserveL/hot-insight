import type { MetadataRoute } from "next";

import { getPublicSiteUrl, getTopics } from "@/lib/api";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const siteUrl = getPublicSiteUrl();
  const staticRoutes: MetadataRoute.Sitemap = [
    { url: siteUrl, changeFrequency: "hourly", priority: 1 },
    { url: `${siteUrl}/weibo`, changeFrequency: "hourly", priority: 0.9 },
    { url: `${siteUrl}/about`, changeFrequency: "monthly", priority: 0.4 },
  ];
  try {
    const topics = await getTopics({ limit: 100 });
    return [
      ...staticRoutes,
      ...topics.items.map((topic) => ({
        url: `${siteUrl}/topics/${topic.id}`,
        lastModified: topic.last_seen_at || undefined,
        changeFrequency: "daily" as const,
        priority: 0.7,
      })),
    ];
  } catch {
    return staticRoutes;
  }
}
