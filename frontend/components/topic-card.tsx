import { ArrowUpRight, Clock3, Flame, Radio } from "lucide-react";
import Link from "next/link";

import { BentoCard } from "@/components/ui/bento-card";
import { TagBadge } from "@/components/ui/tag-badge";
import type { Topic } from "@/lib/types";
import { cn, formatDateTime, formatScore, sourceLabel } from "@/lib/utils";

export function TopicCard({ topic, priority = false }: { topic: Topic; priority?: boolean }) {
  const summary = topic.ai_detail?.takeaway || topic.ai_detail?.summary || topic.ai_error || "洞察生成中，请稍后查看。";
  return (
    <BentoCard
      interactive
      className={cn(
        "group relative flex min-h-[280px] flex-col overflow-hidden",
        priority ? "min-h-[420px] p-6 sm:p-10" : "p-5 sm:p-7",
      )}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <TagBadge tag={topic.tag} />
          <div className="text-sm font-semibold text-[#86868B]">
            {topic.rank === null ? "未排名" : `#${topic.rank}`}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5 rounded-full bg-[#FFF5E6] px-3 py-1 text-sm font-semibold text-[#A66A2C]">
          <Flame className="h-3.5 w-3.5" aria-hidden="true" />
          <span>{formatScore(topic.score)}</span>
        </div>
      </div>
      <Link href={`/topics/${topic.id}`} className="mt-6 block">
        <h2
          className={cn(
            "text-balance font-semibold leading-tight tracking-tight text-[#1D1D1F] transition-colors duration-300 group-hover:text-black",
            priority ? "text-4xl sm:text-5xl" : "text-2xl",
          )}
        >
          {topic.title}
        </h2>
      </Link>
      <p className={cn("mt-5 text-base leading-relaxed text-[#86868B]", priority ? "line-clamp-6 text-lg" : "line-clamp-4")}>
        {summary}
      </p>
      <div className="mt-auto flex flex-wrap items-center justify-between gap-4 pt-10">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm font-medium text-[#86868B]">
          <span className="inline-flex items-center gap-1.5">
            <Clock3 className="h-4 w-4" aria-hidden="true" />
            {formatDateTime(topic.last_seen_at)}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Radio className="h-4 w-4" aria-hidden="true" />
            {sourceLabel(topic.source_id)}
          </span>
        </div>
        <Link
          href={`/topics/${topic.id}`}
          className="inline-flex items-center gap-1 text-sm font-semibold text-[#0066CC] transition hover:underline"
        >
          详情
          <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
        </Link>
      </div>
    </BentoCard>
  );
}
