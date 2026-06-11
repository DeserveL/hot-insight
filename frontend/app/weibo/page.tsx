import type { Metadata } from "next";
import Link from "next/link";

import { TopicCard } from "@/components/topic-card";
import { TagBadge } from "@/components/ui/tag-badge";
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
    <main className="mx-auto max-w-7xl px-4 py-10 sm:px-6">
      <section className="mb-8 border-b border-zinc-200 pb-8">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="mb-3 text-sm font-semibold text-red-600">微博热搜</div>
            <h1 className="text-balance text-4xl font-semibold leading-tight tracking-tight text-ink sm:text-5xl">
              热点列表
            </h1>
            <p className="mt-4 max-w-2xl text-base leading-7 text-muted">
              按标识浏览正在被关注的话题，进入详情页查看 AI 摘要、事实梳理和风险提示。
            </p>
          </div>
          <div className="rounded-card border border-zinc-200 bg-white px-4 py-3 shadow-sm">
            <div className="text-sm font-medium text-muted">当前展示</div>
            <div className="mt-1 text-2xl font-semibold tracking-tight text-ink">{topics.length}</div>
          </div>
        </div>
      </section>

      <div className="mb-7 flex flex-wrap gap-2">
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
        <div className="grid gap-4 md:grid-cols-2">
          {topics.map((topic) => (
            <TopicCard key={topic.id} topic={topic} />
          ))}
        </div>
      ) : (
        <div className="rounded-card border border-dashed border-line bg-white p-10 text-center text-muted">
          当前筛选下暂无热点
        </div>
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
      className={`inline-flex h-10 items-center gap-2 rounded-md border px-3 text-sm font-semibold transition ${
        active
          ? "border-ink bg-ink text-white shadow-sm"
          : "border-zinc-200 bg-white text-muted shadow-sm hover:border-zinc-400 hover:text-ink"
      }`}
    >
      {tag.length === 1 ? (
        <TagBadge tag={tag} className="h-6 min-w-6 border-transparent px-1.5" />
      ) : (
        <span>{tag}</span>
      )}
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
