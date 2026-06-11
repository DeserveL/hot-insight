import type { Metadata } from "next";
import { cache, type ReactNode } from "react";
import { notFound } from "next/navigation";
import { ArrowLeft, ExternalLink } from "lucide-react";

import { BentoCard } from "@/components/ui/bento-card";
import { TagBadge } from "@/components/ui/tag-badge";
import { getPublicSiteUrl, getTopic } from "@/lib/api";
import type { Topic } from "@/lib/types";
import { formatDateTime, formatDurationBetween, formatScore, sourceLabel } from "@/lib/utils";

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
            <TagBadge tag={topic.tag} />
            <span className="rounded-full bg-white px-3 py-1 text-sm font-semibold text-[#86868B] shadow-apple">
              {topic.rank === null ? "未排名" : `排名 #${topic.rank}`}
            </span>
            <span className="rounded-full bg-[#FFF5E6] px-3 py-1 text-sm font-semibold text-[#A66A2C]">
              热度 {formatScore(topic.score)}
            </span>
          </div>

          <h1 className="mt-7 text-balance text-5xl font-semibold leading-tight tracking-tight text-[#1D1D1F] sm:text-6xl">
            {topic.title}
          </h1>

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

          <SourceMaterialView topic={topic} />
          {topic.ai_detail ? <AIDetailView topic={topic} /> : <AIFallback />}
        </article>

        <aside className="lg:sticky lg:top-24 lg:self-start">
          <BentoCard className="p-6 sm:p-7">
            <div className="text-xs font-bold uppercase tracking-widest text-[#A1A1A6]">主题信息</div>
            <div className="mt-6 space-y-5">
              <Info name="来源" value={sourceLabel(topic.source_id)} />
              <Info name="更新时间" value={formatDateTime(topic.last_seen_at)} />
              <Info name="首次出现" value={formatDateTime(topic.first_seen_at)} />
              <Info name="在榜时长" value={formatDurationBetween(topic.first_seen_at, topic.last_seen_at)} />
              <Info name="监测记录" value={`已记录 ${topic.seen_count} 次`} />
            </div>
            <div className="mt-8 flex flex-col gap-3">
              <a
                href={topic.url}
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

function AIDetailView({ topic }: { topic: Topic }) {
  const detail = topic.ai_detail;
  if (!detail) {
    return null;
  }
  return (
    <div className="mt-12">
      <Section title="一句话结论" featured>
        <p>{detail.takeaway || "值得继续关注该热点后续进展。"}</p>
      </Section>
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
      <Section title="AI 评价">
        <p>{detail.commentary || "未能确认"}</p>
      </Section>
      <Section title="风险提示">
        <p>{detail.risk_note || "未能确认"}</p>
        <div className="mt-5 text-sm font-semibold text-[#86868B]">可信度：{detail.confidence || "未标注"}</div>
      </Section>
      <Section title="参考来源">
        {detail.sources.length ? (
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
        ) : (
          <p>未能确认可靠来源链接</p>
        )}
      </Section>
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

function SourceMaterialView({ topic }: { topic: Topic }) {
  const paragraphs = splitSourceExcerpt(topic.source_excerpt);
  return (
    <Section title="微博来源摘要">
      <div className="space-y-5">
        {paragraphs.map((paragraph) => (
          <p key={paragraph}>{paragraph}</p>
        ))}
      </div>
    </Section>
  );
}

function Section({ title, children, featured = false }: { title: string; children: ReactNode; featured?: boolean }) {
  return (
    <section className="border-b border-gray-200/60 py-10 first:border-t">
      <h2 className="text-xs font-bold uppercase tracking-[0.24em] text-[#A1A1A6]">{title}</h2>
      <div
        className={
          featured
            ? "mt-5 text-2xl font-semibold leading-relaxed tracking-tight text-[#1D1D1F] sm:text-3xl"
            : "mt-5 text-lg leading-relaxed text-[#424245]"
        }
      >
        {children}
      </div>
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

function splitSourceExcerpt(value: string | null | undefined) {
  const fallback = "微博公开来源暂未提供更多摘要，可通过微博来源继续查看。";
  const text = (value || "").replace(/\r\n/g, "\n").trim();
  if (!text) {
    return [fallback];
  }

  const explicitParagraphs = text
    .split(/\n+/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean);
  const paragraphs = explicitParagraphs.length > 1 ? explicitParagraphs : splitLongSourceText(text);
  return Array.from(new Set(paragraphs.map((paragraph) => paragraph.trim()).filter(Boolean))).slice(0, 6);
}

function splitLongSourceText(text: string) {
  if (text.length <= 140) {
    return [text];
  }

  const sentences = text.match(/[^。！？!?]+[。！？!?]?/g)?.map((sentence) => sentence.trim()).filter(Boolean) || [];
  if (!sentences.length) {
    return chunkText(text, 140);
  }

  const paragraphs: string[] = [];
  let current = "";
  for (const sentence of sentences) {
    if (current && current.length + sentence.length > 150) {
      paragraphs.push(current);
      current = sentence;
      continue;
    }
    current = `${current}${sentence}`;
  }
  if (current) {
    paragraphs.push(current);
  }
  return paragraphs;
}

function chunkText(text: string, size: number) {
  const chunks: string[] = [];
  for (let index = 0; index < text.length; index += size) {
    chunks.push(text.slice(index, index + size));
  }
  return chunks;
}
