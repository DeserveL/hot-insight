import { ExternalLink, Heart, MessageCircle, Repeat2 } from "lucide-react";
import type { ReactNode } from "react";

import { BentoCard } from "@/components/ui/bento-card";
import type { RealtimePost } from "@/lib/types";
import { formatDateTime, formatScore } from "@/lib/utils";

export function RealtimePosts({
  posts,
  sourceExcerpt,
  sourceUrl,
  mobileUrl,
}: {
  posts: RealtimePost[];
  sourceExcerpt: string;
  sourceUrl: string;
  mobileUrl: string;
}) {
  const discussionUrl = mobileUrl && mobileUrl !== sourceUrl ? mobileUrl : "";

  if (posts.length) {
    return (
      <section className="border-b border-gray-200/60 py-10 first:border-t">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="text-xs font-bold uppercase tracking-[0.24em] text-[#A1A1A6]">热搜实时内容</h2>
            <p className="mt-3 text-sm font-medium leading-relaxed text-[#86868B]">网友讨论，非核实事实</p>
          </div>
          {sourceUrl ? (
            <div className="flex flex-wrap items-center gap-4">
              <a
                href={sourceUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-2 text-sm font-semibold text-[#0066CC] hover:underline"
              >
                在微博查看
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
          ) : null}
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

  return (
    <section className="border-b border-gray-200/60 py-10 first:border-t">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h2 className="text-xs font-bold uppercase tracking-[0.24em] text-[#A1A1A6]">微博来源摘要</h2>
        {sourceUrl ? (
          <div className="flex flex-wrap items-center gap-4">
            <a
              href={sourceUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-2 text-sm font-semibold text-[#0066CC] hover:underline"
            >
              微博来源
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
        ) : null}
      </div>
      <div className="mt-5 space-y-5 text-lg leading-relaxed text-[#424245]">
        {splitSourceExcerpt(sourceExcerpt).map((paragraph) => (
          <p key={paragraph}>{paragraph}</p>
        ))}
      </div>
    </section>
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
  const fallback = "本轮未抓到实时博文，可通过微博来源继续查看。";
  const text = (value || "").replace(/\r\n/g, "\n").trim();
  if (!text) {
    return [fallback];
  }

  const explicitParagraphs = text
    .split(/\n+/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean);
  return Array.from(new Set(explicitParagraphs.length > 1 ? explicitParagraphs : splitLongSourceText(text))).slice(0, 6);
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
