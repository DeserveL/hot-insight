import { ArrowUpRight, Clock3, Flame, Radio } from "lucide-react";
import Link from "next/link";

import { TagBadge } from "@/components/ui/tag-badge";
import type { Topic } from "@/lib/types";
import { cn, formatDateTime, formatScore, sourceLabel } from "@/lib/utils";

export function TopicCard({ topic, priority = false }: { topic: Topic; priority?: boolean }) {
  const summary = topic.ai_detail?.takeaway || topic.ai_detail?.summary || topic.ai_error || "洞察生成中，请稍后查看。";
  return (
    <article
      className={cn(
        "group relative overflow-hidden rounded-card border border-zinc-200/80 bg-white shadow-sm transition hover:border-zinc-300 hover:shadow-soft",
        priority ? "p-6 sm:p-7" : "p-5",
      )}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <TagBadge tag={topic.tag} />
          <div className="text-sm font-semibold text-zinc-400">
            {topic.rank === null ? "未排名" : `#${topic.rank}`}
          </div>
        </div>
        <div className="flex items-center gap-2 rounded-md bg-zinc-50 px-2.5 py-1.5 text-sm font-medium text-zinc-700">
          <Flame className="h-4 w-4 text-orange-500" aria-hidden="true" />
          <span>{formatScore(topic.score)}</span>
        </div>
      </div>
      <Link href={`/topics/${topic.id}`} className="mt-4 block">
        <h2
          className={cn(
            "text-balance font-semibold leading-tight tracking-tight text-ink transition group-hover:text-red-600",
            priority ? "text-3xl sm:text-4xl" : "text-xl",
          )}
        >
          {topic.title}
        </h2>
      </Link>
      <p className={cn("mt-4 text-sm leading-7 text-zinc-600", priority ? "line-clamp-5" : "line-clamp-3")}>
        {summary}
      </p>
      <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-zinc-100 pt-4">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-muted">
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
          className="inline-flex items-center gap-1 text-sm font-semibold text-ink transition group-hover:text-red-600"
        >
          详情
          <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
        </Link>
      </div>
    </article>
  );
}
