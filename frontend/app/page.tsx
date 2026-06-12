import { ArrowUpRight, TrendingUp } from "lucide-react";
import Link from "next/link";

import { TopicCard } from "@/components/topic-card";
import { BentoCard } from "@/components/ui/bento-card";
import { TagBadge } from "@/components/ui/tag-badge";
import { getTopics, getTrendsSummary } from "@/lib/api";
import type { Topic, TrendsSummary } from "@/lib/types";
import { formatDateTime, formatScore, sourceLabel } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const { summary, topics } = await loadHomeData();
  const heroTopic = topics[0];
  const restTopics = topics.slice(1, 7);
  const tagCount = summary?.tags?.length ?? 0;

  return (
    <main className="bg-surface pb-20">
      <section className="mx-auto max-w-6xl px-5 py-16 sm:px-6 sm:py-20 lg:py-24">
        <div className="max-w-3xl">
          <h1 className="text-balance text-6xl font-semibold leading-none tracking-tight text-[#1D1D1F] sm:text-7xl">
            微博热点洞察
          </h1>
          <p className="mt-7 max-w-2xl text-xl leading-relaxed text-[#86868B]">
            聚合正在升温的话题，整理事件脉络、关键事实与风险提示，让热点阅读更清晰。
          </p>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-5 sm:px-6">
        <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
          <div className="md:col-span-2">
            {heroTopic ? <FocusCard topic={heroTopic} /> : <EmptyPanel />}
          </div>
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 md:grid-cols-1">
            <Metric label="累计热点" value={summary?.topic_count ?? 0} />
            <Metric label="关注标识" value={tagCount} />
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-5 py-16 sm:px-6">
        <div className="mb-8 flex items-end justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-[#9A6A35]">
              <TrendingUp className="h-4 w-4" aria-hidden="true" />
              最新洞察
            </div>
            <h2 className="mt-3 text-4xl font-semibold tracking-tight text-[#1D1D1F]">正在升温</h2>
          </div>
          <Link href="/weibo" className="text-sm font-semibold text-[#0066CC] transition hover:underline">
            全部热点
          </Link>
        </div>
        {restTopics.length ? (
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
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

function FocusCard({ topic }: { topic: Topic }) {
  const summary = topic.ai_detail?.takeaway || topic.ai_detail?.summary || topic.ai_error || "洞察生成中，请稍后查看。";
  const displayTag = topic.peak_tag || topic.tag;
  const displayRank = topic.best_rank ?? topic.rank;
  const displayScore = topic.peak_score ?? topic.score;
  return (
    <BentoCard interactive className="flex min-h-[440px] flex-col justify-between p-6 sm:p-10">
      <div>
        <div className="mb-8 flex flex-wrap items-center justify-between gap-4">
          <span className="rounded-full bg-[#FFF1E6] px-3 py-1 text-xs font-bold uppercase tracking-wider text-[#A55A2A]">
            当前焦点
          </span>
          <span className="rounded-full bg-[#FFF5E6] px-3 py-1 text-sm font-semibold text-[#A66A2C]">
            峰值热度 {formatScore(displayScore)}
          </span>
        </div>
        <div className="mb-5 flex items-center gap-3">
          <TagBadge tag={displayTag} />
          <span className="text-sm font-semibold text-[#86868B]">
            {displayRank === null ? "未排名" : `最高 #${displayRank}`}
          </span>
        </div>
        <h2 className="text-balance text-4xl font-semibold leading-tight tracking-tight text-[#1D1D1F] sm:text-5xl">
          {topic.title}
        </h2>
        <p className="mt-6 max-w-2xl text-lg leading-relaxed text-[#86868B]">{summary}</p>
      </div>
      <div className="mt-12 flex flex-wrap items-center justify-between gap-4 text-sm font-medium text-[#86868B]">
        <span>
          {formatDateTime(topic.last_seen_at)} · {sourceLabel(topic.source_id)}
        </span>
        <Link href={`/topics/${topic.id}`} className="inline-flex items-center gap-1 font-semibold text-[#0066CC] hover:underline">
          查看详情
          <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
        </Link>
      </div>
    </BentoCard>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <BentoCard className="flex min-h-[160px] flex-col justify-center">
      <div className="text-5xl font-semibold tracking-tight text-[#1D1D1F]">{value}</div>
      <div className="mt-2 text-sm font-semibold text-[#86868B]">{label}</div>
    </BentoCard>
  );
}

function EmptyPanel() {
  return (
    <BentoCard className="flex min-h-[220px] items-center justify-center text-center text-[#86868B]">
      暂无热点数据
    </BentoCard>
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
