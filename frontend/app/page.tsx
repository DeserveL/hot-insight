import { Activity, Sparkles, TrendingUp } from "lucide-react";
import Link from "next/link";

import { TopicCard } from "@/components/topic-card";
import { ButtonLink } from "@/components/ui/button";
import { getTopics, getTrendsSummary } from "@/lib/api";
import type { Topic, TrendsSummary } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const { summary, topics } = await loadHomeData();
  const heroTopic = topics[0];
  const restTopics = topics.slice(1, 7);
  const tagCount = summary?.tags?.length ?? 0;
  const channelCount = summary?.channels?.filter((item) => item.enabled).length ?? 1;

  return (
    <main className="pb-16">
      <section className="border-b border-zinc-200/80 bg-white">
        <div className="mx-auto grid max-w-7xl gap-10 px-4 py-12 sm:px-6 lg:grid-cols-[0.95fr_1.05fr] lg:py-16">
          <div className="flex flex-col justify-between">
            <div>
              <div className="mb-7 inline-flex items-center gap-2 rounded-md border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm font-semibold text-zinc-700">
                <Sparkles className="h-4 w-4 text-red-500" aria-hidden="true" />
                AI 辅助热点阅读
              </div>
              <h1 className="max-w-3xl text-balance text-5xl font-semibold leading-tight tracking-tight text-ink sm:text-6xl">
                微博热点洞察
              </h1>
              <p className="mt-6 max-w-2xl text-lg leading-8 text-muted">
                聚合正在升温的话题，整理事件脉络、关键事实与风险提示，让热点阅读更清晰。
              </p>
              <div className="mt-8 flex flex-wrap gap-3">
                <ButtonLink href="/weibo">查看热榜</ButtonLink>
                <ButtonLink href="/about" variant="secondary">
                  了解说明
                </ButtonLink>
              </div>
            </div>
            <div className="mt-12 grid max-w-2xl grid-cols-3 gap-3">
              <Metric label="累计热点" value={summary?.topic_count ?? 0} />
              <Metric label="关注标识" value={tagCount} />
              <Metric label="频道" value={channelCount} />
            </div>
          </div>
          <div>
            <div className="mb-4 flex items-center justify-between gap-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-zinc-500">
                <Activity className="h-4 w-4 text-red-500" aria-hidden="true" />
                当前焦点
              </div>
              <Link href="/weibo" className="text-sm font-semibold text-zinc-500 transition hover:text-ink">
                全部热点
              </Link>
            </div>
            {heroTopic ? <TopicCard topic={heroTopic} priority /> : <EmptyPanel />}
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-4 py-12 sm:px-6">
        <div className="mb-7 flex items-end justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-red-600">
              <TrendingUp className="h-4 w-4" aria-hidden="true" />
              最新洞察
            </div>
            <h2 className="mt-2 text-3xl font-semibold tracking-tight text-ink">正在升温</h2>
          </div>
          <Link href="/weibo" className="text-sm font-semibold text-muted transition hover:text-ink">
            全部热点
          </Link>
        </div>
        {restTopics.length ? (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {restTopics.map((topic) => (
              <TopicCard key={topic.id} topic={topic} />
            ))}
          </div>
        ) : (
          <EmptyPanel />
        )}
      </section>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-card border border-zinc-200 bg-white p-4 shadow-sm">
      <div className="text-2xl font-semibold tracking-tight text-ink">{value}</div>
      <div className="mt-1 text-sm font-medium text-muted">{label}</div>
    </div>
  );
}

function EmptyPanel() {
  return (
    <div className="rounded-card border border-dashed border-line bg-white p-8 text-center text-muted">
      暂无热点数据
    </div>
  );
}

async function loadHomeData(): Promise<{ summary: TrendsSummary | null; topics: Topic[] }> {
  try {
    const [summary, topicList] = await Promise.all([getTrendsSummary(), getTopics({ limit: 8 })]);
    return { summary, topics: topicList.items };
  } catch {
    return { summary: null, topics: [] };
  }
}
