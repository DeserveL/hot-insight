import { ExternalLink, Heart, MessageCircle, Repeat2 } from "lucide-react";
import type { ReactNode } from "react";

import { BentoCard } from "@/components/ui/bento-card";
import type { RealtimePost } from "@/lib/types";
import { formatDateTime, formatScore } from "@/lib/utils";

export function RealtimePosts({
  posts,
  sourceExcerpt,
  sourceExcerptOrigin,
  sourceUrl,
  mobileUrl,
}: {
  posts: RealtimePost[];
  sourceExcerpt: string;
  sourceExcerptOrigin?: "official" | "mobile" | "";
  sourceUrl: string;
  mobileUrl: string;
}) {
  const discussionUrl = mobileUrl && mobileUrl !== sourceUrl ? mobileUrl : "";
  const paragraphs = splitSourceExcerpt(sourceExcerpt);
  const origin = normalizeSourceExcerptOrigin(sourceExcerptOrigin);
  const shouldShowSourceExcerpt = paragraphs.length > 0 && (origin === "official" || posts.length === 0);

  if (!shouldShowSourceExcerpt && !posts.length) {
    return null;
  }

  return (
    <>
      {shouldShowSourceExcerpt ? (
        <SourceExcerptSection
          paragraphs={paragraphs}
          origin={origin}
          sourceUrl={sourceUrl}
          discussionUrl={discussionUrl}
        />
      ) : null}
      {posts.length ? (
        <RealtimePostSection posts={posts} sourceUrl={sourceUrl} discussionUrl={discussionUrl} />
      ) : null}
    </>
  );
}

function SourceExcerptSection({
  paragraphs,
  origin,
  sourceUrl,
  discussionUrl,
}: {
  paragraphs: string[];
  origin: "official" | "mobile";
  sourceUrl: string;
  discussionUrl: string;
}) {
  const title = origin === "official" ? "微博官方详情" : "微博讨论摘要";
  const subtitle = origin === "official" ? "热搜详情页材料，作为事件主线参考" : "移动端讨论材料整理";
  const visibleParagraphs = paragraphs.slice(0, 3);
  const hiddenParagraphs = paragraphs.slice(3);

  return (
    <section className="border-b border-gray-200/60 py-10 first:border-t">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-xs font-bold uppercase tracking-[0.24em] text-[#A1A1A6]">{title}</h2>
          <p className="mt-3 text-sm font-medium leading-relaxed text-[#86868B]">{subtitle}</p>
        </div>
        <SourceLinks sourceUrl={sourceUrl} discussionUrl={discussionUrl} sourceLabel="微博来源" />
      </div>
      <BentoCard className="mt-6 p-5 sm:p-6">
        <div className="space-y-4 text-base leading-7 text-[#424245]">
          {visibleParagraphs.map((paragraph) => (
            <p key={paragraph} className="break-words">
              {paragraph}
            </p>
          ))}
          {hiddenParagraphs.length ? (
            <details className="group">
              <summary className="inline-flex cursor-pointer select-none list-none items-center text-sm font-semibold text-[#0066CC] hover:underline [&::-webkit-details-marker]:hidden">
                展开更多
              </summary>
              <div className="mt-4 space-y-4">
                {hiddenParagraphs.map((paragraph) => (
                  <p key={paragraph} className="break-words">
                    {paragraph}
                  </p>
                ))}
              </div>
            </details>
          ) : null}
        </div>
      </BentoCard>
    </section>
  );
}

function RealtimePostSection({
  posts,
  sourceUrl,
  discussionUrl,
}: {
  posts: RealtimePost[];
  sourceUrl: string;
  discussionUrl: string;
}) {
  return (
    <section className="border-b border-gray-200/60 py-10 first:border-t">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-xs font-bold uppercase tracking-[0.24em] text-[#A1A1A6]">热搜实时内容</h2>
          <p className="mt-3 text-sm font-medium leading-relaxed text-[#86868B]">网友讨论，非核实事实</p>
        </div>
        <SourceLinks sourceUrl={sourceUrl} discussionUrl={discussionUrl} sourceLabel="在微博查看" />
      </div>
      <div className="mt-6 grid gap-4">
        {posts.map((post, index) => (
          <BentoCard key={`${post.url || post.text}-${index}`} className="p-5 sm:p-6">
            <div className="flex flex-wrap items-center justify-between gap-3 text-sm font-semibold text-[#86868B]">
              <span className="break-words text-[#1D1D1F]">{post.author ? `@${post.author}` : "微博用户"}</span>
              <span>{formatDateTime(post.created_at)}</span>
            </div>
            <p className="mt-4 whitespace-pre-wrap break-words text-base leading-relaxed text-[#424245]">{post.text}</p>
            <div className="mt-5 flex flex-wrap items-center justify-between gap-4">
              <div className="flex flex-wrap items-center gap-4 text-sm font-medium text-[#86868B]">
                <Metric icon={<Repeat2 className="h-4 w-4" />} value={post.reposts} />
                <Metric icon={<MessageCircle className="h-4 w-4" />} value={post.comments} />
                <Metric icon={<Heart className="h-4 w-4" />} value={post.attitudes} />
              </div>
              {post.url ? (
                <a
                  href={post.url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-sm font-semibold text-[#0066CC] hover:underline"
                >
                  原文
                  <ExternalLink className="h-4 w-4" aria-hidden="true" />
                </a>
              ) : null}
            </div>
          </BentoCard>
        ))}
      </div>
    </section>
  );
}

function SourceLinks({
  sourceUrl,
  discussionUrl,
  sourceLabel,
}: {
  sourceUrl: string;
  discussionUrl: string;
  sourceLabel: string;
}) {
  if (!sourceUrl) {
    return null;
  }

  return (
    <div className="flex flex-wrap items-center gap-4">
      <a
        href={sourceUrl}
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-2 text-sm font-semibold text-[#0066CC] hover:underline"
      >
        {sourceLabel}
        <ExternalLink className="h-4 w-4" aria-hidden="true" />
      </a>
      {discussionUrl ? (
        <a
          href={discussionUrl}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-2 text-sm font-semibold text-[#6E6E73] hover:underline"
        >
          实时讨论
          <ExternalLink className="h-4 w-4" aria-hidden="true" />
        </a>
      ) : null}
    </div>
  );
}

function Metric({ icon, value }: { icon: ReactNode; value: number | null }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      {icon}
      {formatScore(value)}
    </span>
  );
}

function splitSourceExcerpt(value: string | null | undefined) {
  const text = cleanSourceExcerpt(value);
  if (!text) {
    return [];
  }

  const explicitParagraphs = text
    .split(/\n+/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean);
  return Array.from(new Set(explicitParagraphs.length > 1 ? explicitParagraphs : splitLongSourceText(text))).slice(0, 8);
}

function cleanSourceExcerpt(value: string | null | undefined) {
  return (value || "")
    .replace(/\r\n/g, "\n")
    .replace(/展开全文\s*[cC]?/g, "")
    .replace(/收起全文/g, "")
    .replace(/查看全文/g, "")
    .replace(/[ \t]+/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function normalizeSourceExcerptOrigin(value: string | null | undefined): "official" | "mobile" {
  return value === "official" ? "official" : "mobile";
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
