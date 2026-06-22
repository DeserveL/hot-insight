/* eslint-disable @next/next/no-img-element -- 微博图片走同源代理，避免浏览器直连触发防盗链。 */
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
  sourceExcerptOrigin?: "official" | "mobile" | "";
  sourceUrl: string;
  mobileUrl: string;
}) {
  const discussionUrl = mobileUrl && mobileUrl !== sourceUrl ? mobileUrl : "";
  const visiblePosts = posts.filter((post) => post.text || post.images?.length || post.url);
  const featuredPost = visiblePosts.find((post) => post.is_featured) || null;
  const relatedPosts = visiblePosts.filter((post) => post !== featuredPost);
  const paragraphs = splitSourceExcerpt(sourceExcerpt);

  if (!visiblePosts.length && !paragraphs.length) {
    return null;
  }

  return (
    <>
      {featuredPost ? (
        <FeaturedPostSection post={featuredPost} sourceUrl={sourceUrl} discussionUrl={discussionUrl} />
      ) : null}
      {relatedPosts.length ? (
        <RelatedPostsSection posts={relatedPosts} sourceUrl={sourceUrl} discussionUrl={discussionUrl} />
      ) : null}
      {!visiblePosts.length && paragraphs.length ? (
        <SourceExcerptFallback paragraphs={paragraphs} sourceUrl={sourceUrl} discussionUrl={discussionUrl} />
      ) : null}
    </>
  );
}

function FeaturedPostSection({
  post,
  sourceUrl,
  discussionUrl,
}: {
  post: RealtimePost;
  sourceUrl: string;
  discussionUrl: string;
}) {
  return (
    <section className="border-b border-gray-200/60 py-10 first:border-t">
      <SectionHeader title="精选微博" sourceUrl={sourceUrl} discussionUrl={discussionUrl} sourceLabel="在微博查看" />
      <BentoCard className="mt-6 overflow-hidden p-0">
        <div className="grid gap-0 lg:grid-cols-[minmax(0,1fr)_280px]">
          <div className="p-5 sm:p-7">
            <PostMeta post={post} />
            <p className="mt-5 whitespace-pre-wrap break-words text-lg leading-relaxed text-[#1D1D1F]">{post.text}</p>
            <PostFooter post={post} />
          </div>
          {post.images?.length ? (
            <div className="border-t border-gray-200/60 bg-[#F5F5F7] p-3 lg:border-l lg:border-t-0">
              <ImageGrid images={post.images} featured />
            </div>
          ) : null}
        </div>
      </BentoCard>
    </section>
  );
}

function RelatedPostsSection({
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
      <SectionHeader title="相关讨论" sourceUrl={sourceUrl} discussionUrl={discussionUrl} sourceLabel="在微博查看" />
      <div className="mt-6 grid gap-4">
        {posts.map((post, index) => (
          <BentoCard key={`${post.url || post.text}-${index}`} className="p-5 sm:p-6">
            <PostMeta post={post} />
            <p className="mt-4 whitespace-pre-wrap break-words text-base leading-relaxed text-[#424245]">{post.text}</p>
            {post.images?.length ? (
              <div className="mt-5">
                <ImageGrid images={post.images} />
              </div>
            ) : null}
            <PostFooter post={post} />
          </BentoCard>
        ))}
      </div>
    </section>
  );
}

function SourceExcerptFallback({
  paragraphs,
  sourceUrl,
  discussionUrl,
}: {
  paragraphs: string[];
  sourceUrl: string;
  discussionUrl: string;
}) {
  const visibleParagraphs = paragraphs.slice(0, 3);
  const hiddenParagraphs = paragraphs.slice(3);

  return (
    <section className="border-b border-gray-200/60 py-10 first:border-t">
      <SectionHeader title="相关信息" sourceUrl={sourceUrl} discussionUrl={discussionUrl} sourceLabel="微博来源" />
      <BentoCard className="mt-6 p-5 sm:p-6">
        <div className="space-y-4 text-base leading-7 text-[#424245]">
          {visibleParagraphs.map((paragraph) => (
            <p key={paragraph} className="break-words">
              {paragraph}
            </p>
          ))}
          {hiddenParagraphs.length ? (
            <details>
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

function SectionHeader({
  title,
  sourceUrl,
  discussionUrl,
  sourceLabel,
}: {
  title: string;
  sourceUrl: string;
  discussionUrl: string;
  sourceLabel: string;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-4">
      <h2 className="text-xs font-bold uppercase tracking-[0.24em] text-[#A1A1A6]">{title}</h2>
      <SourceLinks sourceUrl={sourceUrl} discussionUrl={discussionUrl} sourceLabel={sourceLabel} />
    </div>
  );
}

function PostMeta({ post }: { post: RealtimePost }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 text-sm font-semibold text-[#86868B]">
      <span className="break-words text-[#1D1D1F]">{post.author ? `@${post.author}` : "微博用户"}</span>
      <span>{formatDateTime(post.created_at)}</span>
    </div>
  );
}

function PostFooter({ post }: { post: RealtimePost }) {
  return (
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
  );
}

function ImageGrid({ images, featured = false }: { images: string[]; featured?: boolean }) {
  const visibleImages = images.map(getWeiboImageProxyPath).filter(Boolean).slice(0, featured ? 1 : 4);
  if (!visibleImages.length) {
    return null;
  }

  if (featured) {
    return (
      <img
        src={visibleImages[0]}
        alt=""
        aria-hidden="true"
        className="aspect-[4/5] h-full min-h-64 w-full rounded-2xl object-cover"
      />
    );
  }

  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {visibleImages.map((image) => (
        <img
          key={image}
          src={image}
          alt=""
          aria-hidden="true"
          className="aspect-square w-full rounded-2xl bg-[#F5F5F7] object-cover"
        />
      ))}
    </div>
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

function getWeiboImageProxyPath(url: string | null | undefined) {
  if (!isSinaImgUrl(url)) {
    return "";
  }
  return `/api/weibo-image?url=${encodeURIComponent(url)}`;
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
