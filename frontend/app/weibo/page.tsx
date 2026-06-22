import type { Metadata } from "next";
import Link from "next/link";

import { TopicCard } from "@/components/topic-card";
import { BentoCard } from "@/components/ui/bento-card";
import { getTopics, getTrendsSummary } from "@/lib/api";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "微博热搜",
  description: "微博热搜 AI 洞察列表。",
};

const tags = ["爆", "沸", "热"];

export default async function WeiboPage({
  searchParams,
}: {
  searchParams?: Promise<{ tag?: string }>;
}) {
  const params = (await searchParams) || {};
  const activeTag = params.tag || "";
  const { topics, counts, totalCount } = await loadWeiboData(activeTag);

  return (
    <main className="mx-auto max-w-6xl bg-surface px-5 py-16 sm:px-6 lg:py-20">
      <section className="mb-10">
        <div className="flex flex-col gap-8 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-3xl">
            <h1 className="text-balance text-5xl font-semibold leading-none tracking-tight text-[#1D1D1F] sm:text-6xl">
              微博热搜列表
            </h1>
            <p className="mt-6 max-w-2xl text-lg leading-relaxed text-[#86868B]">
              按标识浏览正在被关注的话题，进入详情页查看 AI 摘要、事实梳理和风险提示。
            </p>
          </div>
          <BentoCard className="min-w-[160px] px-6 py-5">
            <div className="text-sm font-semibold text-[#86868B]">当前展示</div>
            <div className="mt-1 text-4xl font-semibold tracking-tight text-[#1D1D1F]">{topics.length}</div>
          </BentoCard>
        </div>
      </section>

      <div className="mb-10 inline-flex max-w-full gap-1 overflow-x-auto rounded-full bg-[#E8E8ED] p-1">
        <FilterLink href="/weibo" active={!activeTag} tag="全部" count={totalCount} />
        {tags.map((tag) => (
          <FilterLink
            key={tag}
            href={`/weibo?tag=${encodeURIComponent(tag)}`}
            active={activeTag === tag}
            tag={tag}
            count={counts.get(tag) || 0}
          />
        ))}
      </div>

      {topics.length ? (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
          {topics.map((topic) => (
            <TopicCard key={topic.id} topic={topic} />
          ))}
        </div>
      ) : (
        <BentoCard className="flex min-h-[240px] items-center justify-center text-center text-[#86868B]">
          当前筛选下暂无热点
        </BentoCard>
      )}
    </main>
  );
}

function FilterLink({
  href,
  active,
  tag,
  count,
}: {
  href: string;
  active: boolean;
  tag: string;
  count: number;
}) {
  return (
    <Link
      href={href}
      className={`inline-flex h-10 shrink-0 items-center gap-2 rounded-full px-4 text-sm font-semibold transition-all duration-300 ease-out ${
        active
          ? "bg-white text-[#1D1D1F] shadow-[0_2px_10px_rgba(0,0,0,0.08)]"
          : "text-[#86868B] hover:text-[#1D1D1F]"
      }`}
    >
      <span>{tag}</span>
      <span className="text-xs opacity-70">{count}</span>
    </Link>
  );
}

async function loadWeiboData(tag: string) {
  try {
    const [topicList, summary] = await Promise.all([getTopics({ tag, limit: 50 }), getTrendsSummary()]);
    return {
      topics: topicList.items,
      counts: new Map(summary.tags.map((item) => [item.tag, item.count])),
      totalCount: summary.topic_count,
    };
  } catch {
    return { topics: [], counts: new Map<string, number>(), totalCount: 0 };
  }
}
