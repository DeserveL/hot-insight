import type { Metadata } from "next";
import { cache, type ReactNode } from "react";
import { notFound } from "next/navigation";
import { ArrowLeft, ExternalLink } from "lucide-react";

import { BentoCard } from "@/components/ui/bento-card";
import { HeatTrend } from "@/components/heat-trend";
import { RealtimePosts } from "@/components/realtime-posts";
import { TagBadge } from "@/components/ui/tag-badge";
import { getPublicSiteUrl, getTopic } from "@/lib/api";
import type { Topic } from "@/lib/types";
import { confidenceLabel, formatDateTime, formatDurationBetween, formatScore, sourceLabel } from "@/lib/utils";

export const dynamic = "force-dynamic";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  const topic = await loadTopic(id);
  if (!topic) {
    return { title: "热点不存在" };
  }
  const description = topic.ai_detail?.takeaway || topic.ai_detail?.summary || topic.source_excerpt || `${topic.title}，微博热搜 AI 洞察。`;
  const coverImageUrl = getAbsoluteWeiboImageProxyUrl(topic.cover_image_url);
  return {
    title: topic.title,
    description,
    openGraph: {
      title: topic.title,
      description,
      url: `${getPublicSiteUrl()}/topics/${topic.id}`,
      type: "article",
      images: coverImageUrl ? [{ url: coverImageUrl }] : undefined,
    },
  };
}

export default async function TopicDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const topic = await loadTopic(id);
  if (!topic) {
    notFound();
  }
  const jsonLd = buildJsonLd(topic);
  const coverImageUrl = getWeiboImageProxyPath(topic.cover_image_url);
  const peakTag = topic.peak_tag || topic.tag;
  const bestRank = topic.best_rank ?? topic.rank;
  const peakScore = topic.peak_score ?? topic.score;
  const mobileUrl = topic.mobile_url || "";
  const sourceUrl = getPreferredSourceUrl(topic);
  const takeaway = topic.ai_detail?.takeaway || "";

  return (
    <main className="mx-auto max-w-6xl bg-surface px-5 py-12 sm:px-6 lg:py-16">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd).replace(/</g, "\\u003c") }}
      />
      <a
        href="/weibo"
        className="mb-10 inline-flex items-center gap-2 text-sm font-semibold text-[#86868B] transition hover:text-[#1D1D1F]"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        返回热榜
      </a>

      <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_340px]">
        <article className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <TagBadge tag={peakTag} />
            <span className="rounded-full bg-white px-3 py-1 text-sm font-semibold text-[#86868B] shadow-apple">
              {bestRank === null ? "未排名" : `最高排名 #${bestRank}`}
            </span>
            <span className="rounded-full bg-[#FFF5E6] px-3 py-1 text-sm font-semibold text-[#A66A2C]">
              峰值热度 {formatScore(peakScore)}
            </span>
          </div>

          <h1 className="mt-7 text-balance text-5xl font-semibold leading-tight tracking-tight text-[#1D1D1F] sm:text-6xl">
            {topic.title}
          </h1>

          {takeaway ? (
            <p className="mt-7 text-2xl font-semibold leading-relaxed tracking-tight text-[#1D1D1F] sm:text-3xl">
              {takeaway}
            </p>
          ) : null}

          {coverImageUrl ? (
            <div className="mt-10 overflow-hidden rounded-2xl bg-white shadow-apple sm:rounded-3xl">
              {/* eslint-disable-next-line @next/next/no-img-element -- 微博图片走同源代理，避免浏览器直连触发防盗链。 */}
              <img
                src={coverImageUrl}
                alt={topic.title}
                className="aspect-[16/9] w-full rounded-2xl object-cover sm:rounded-3xl"
              />
            </div>
          ) : null}

          <RealtimePosts
            posts={topic.realtime_posts || []}
            sourceExcerpt={topic.source_excerpt}
            sourceExcerptOrigin={topic.source_excerpt_origin}
            sourceUrl={sourceUrl}
            mobileUrl={mobileUrl}
          />
          {topic.ai_detail ? <AIDetailView topic={topic} /> : <AIFallback />}
        </article>

        <aside className="lg:sticky lg:top-24 lg:self-start">
          <BentoCard className="p-6 sm:p-7">
            <div className="text-xs font-bold uppercase tracking-widest text-[#A1A1A6]">主题信息</div>
            <div className="mt-6 space-y-5">
              <Info name="来源" value={sourceLabel(topic.source_id)} />
              <Info name="峰值状态" value={formatPeakStatus(topic)} />
              <Info name="当前状态" value={formatCurrentStatus(topic)} />
              <Info name="更新时间" value={formatDateTime(topic.last_seen_at)} />
              <Info name="首次出现" value={formatDateTime(topic.first_seen_at)} />
              <Info name="在榜时长" value={formatDurationBetween(topic.first_seen_at, topic.last_seen_at)} />
              <Info name="观测轮次" value={`已观测 ${topic.seen_count} 轮`} />
            </div>
            <div className="mt-7">
              <HeatTrend observations={topic.observations || []} />
            </div>
            <div className="mt-8 flex flex-col gap-3">
              <a
                href={sourceUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex h-11 items-center justify-center gap-2 rounded-full bg-[#1D1D1F] px-4 text-sm font-semibold text-white shadow-apple transition-all duration-300 ease-out hover:scale-[1.01] hover:bg-black hover:shadow-apple-lg"
              >
                微博来源
                <ExternalLink className="h-4 w-4" aria-hidden="true" />
              </a>
              <a
                href="/weibo"
                className="inline-flex h-11 items-center justify-center rounded-full bg-[#F5F5F7] px-4 text-sm font-semibold text-[#1D1D1F] transition-all duration-300 ease-out hover:scale-[1.01]"
              >
                查看更多热点
              </a>
            </div>
          </BentoCard>
        </aside>
      </div>
    </main>
  );
}

function Info({ name, value }: { name: string; value: string }) {
  return (
    <div>
      <div className="text-xs font-bold uppercase tracking-widest text-[#A1A1A6]">{name}</div>
      <div className="mt-1 break-words text-base font-semibold text-[#1D1D1F]">{value}</div>
    </div>
  );
}

function getPreferredSourceUrl(topic: Topic) {
  if (isWeiboOfficialHotDetailUrl(topic.url)) {
    return topic.url;
  }
  return topic.mobile_url || topic.url;
}

function isWeiboOfficialHotDetailUrl(value: string) {
  try {
    const url = new URL(value);
    return (
      url.protocol === "https:" &&
      url.hostname === "weibo.com" &&
      url.pathname.startsWith("/a/hot/") &&
      !url.pathname.startsWith("/a/hot/realtime/") &&
      url.pathname.endsWith(".html")
    );
  } catch {
    return false;
  }
}

function formatPeakStatus(topic: Topic) {
  const tag = topic.peak_tag || topic.tag || "无标识";
  const rank = topic.best_rank ?? topic.rank;
  const score = topic.peak_score ?? topic.score;
  return `${tag} · ${rank === null ? "未排名" : `最高 #${rank}`} · 峰值 ${formatScore(score)}`;
}

function formatCurrentStatus(topic: Topic) {
  const tag = topic.tag || "无标识";
  return `${tag} · ${topic.rank === null ? "未排名" : `当前 #${topic.rank}`} · 当前 ${formatScore(topic.score)}`;
}

function AIDetailView({ topic }: { topic: Topic }) {
  const detail = topic.ai_detail;
  if (!detail) {
    return null;
  }
  return (
    <div className="mt-12">
      <div className="mb-2">
        <h2 className="text-xs font-bold uppercase tracking-[0.24em] text-[#A1A1A6]">AI 洞察</h2>
        <p className="mt-3 text-sm font-medium leading-relaxed text-[#86868B]">由 AI 基于以上公开内容整理，仅供参考</p>
      </div>
      <Section title="热点梳理">
        <p>{detail.summary}</p>
      </Section>
      <Section title="关键事实">
        <ul className="space-y-4">
          {(detail.facts.length ? detail.facts : ["未能确认"]).map((fact) => (
            <li key={fact} className="flex gap-3">
              <span className="mt-3 h-1.5 w-1.5 shrink-0 rounded-full bg-[#C7B299]" />
              <span>{fact}</span>
            </li>
          ))}
        </ul>
      </Section>
      <Section title="观察">
        <p>{detail.commentary || "未能确认"}</p>
      </Section>
      <Section title="风险提示">
        <p>{detail.risk_note || "未能确认"}</p>
        <div className="mt-5 text-sm font-semibold text-[#86868B]">可信度：{confidenceLabel(detail.confidence)}</div>
      </Section>
      {detail.sources.length ? (
        <Section title="参考来源">
          <ul className="space-y-3">
            {detail.sources.map((source) => (
              <li key={`${source.title}-${source.url}`}>
                <a
                  href={source.url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-2 font-semibold text-[#0066CC] hover:underline"
                >
                  {source.title || source.url}
                  <ExternalLink className="h-4 w-4" aria-hidden="true" />
                </a>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
    </div>
  );
}

function AIFallback() {
  return (
    <BentoCard className="mt-10 text-[#86868B]">
      洞察生成中，请稍后查看。
    </BentoCard>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-b border-gray-200/60 py-10 first:border-t">
      <h2 className="text-xs font-bold uppercase tracking-[0.24em] text-[#A1A1A6]">{title}</h2>
      <div className="mt-5 text-lg leading-relaxed text-[#424245]">{children}</div>
    </section>
  );
}

const loadTopic = cache(async function loadTopic(id: string) {
  try {
    return await getTopic(id);
  } catch {
    return null;
  }
});

function buildJsonLd(topic: Topic) {
  const image = getAbsoluteWeiboImageProxyUrl(topic.cover_image_url);
  return {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: topic.title,
    datePublished: topic.first_seen_at,
    dateModified: topic.last_seen_at,
    description: topic.ai_detail?.takeaway || topic.ai_detail?.summary || topic.source_excerpt || topic.title,
    url: `${getPublicSiteUrl()}/topics/${topic.id}`,
    image: image || undefined,
  };
}

function getWeiboImageProxyPath(url: string | null | undefined) {
  if (!isSinaImgUrl(url)) {
    return "";
  }
  return `/api/weibo-image?url=${encodeURIComponent(url)}`;
}

function getAbsoluteWeiboImageProxyUrl(url: string | null | undefined) {
  const path = getWeiboImageProxyPath(url);
  return path ? `${getPublicSiteUrl()}${path}` : "";
}

function isSinaImgUrl(value: string | null | undefined): value is string {
  if (!value) {
    return false;
  }
  try {
    const url = new URL(value);
    const hostname = url.hostname.toLowerCase();
    return url.protocol === "https:" && (hostname === "sinaimg.cn" || hostname.endsWith(".sinaimg.cn"));
  } catch {
    return false;
  }
}
