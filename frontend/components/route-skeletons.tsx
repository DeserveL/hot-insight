import { BentoCard } from "@/components/ui/bento-card";
import { cn } from "@/lib/utils";

function SkeletonBlock({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-full bg-white/80 shadow-sm", className)} aria-hidden="true" />;
}

function SkeletonCard({ className }: { className?: string }) {
  return (
    <BentoCard className={cn("min-h-[280px] p-5 sm:p-7", className)}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <SkeletonBlock className="h-8 w-8 rounded-full bg-[#EFEFF4]" />
          <SkeletonBlock className="h-4 w-20 bg-[#EFEFF4]" />
        </div>
        <SkeletonBlock className="h-7 w-28 bg-[#FFF5E6]" />
      </div>
      <div className="mt-8 space-y-3">
        <SkeletonBlock className="h-7 w-5/6 rounded-xl bg-[#EFEFF4]" />
        <SkeletonBlock className="h-7 w-2/3 rounded-xl bg-[#EFEFF4]" />
      </div>
      <div className="mt-8 space-y-3">
        <SkeletonBlock className="h-4 w-full rounded-lg bg-[#F0F0F3]" />
        <SkeletonBlock className="h-4 w-4/5 rounded-lg bg-[#F0F0F3]" />
      </div>
      <div className="mt-14 flex items-center justify-between">
        <SkeletonBlock className="h-4 w-28 rounded-lg bg-[#EFEFF4]" />
        <SkeletonBlock className="h-4 w-16 rounded-lg bg-[#EFEFF4]" />
      </div>
    </BentoCard>
  );
}

export function HomePageSkeleton() {
  return (
    <main className="bg-surface pb-20">
      <section className="mx-auto max-w-6xl px-5 py-16 sm:px-6 sm:py-20 lg:py-24">
        <div className="max-w-3xl">
          <SkeletonBlock className="h-16 w-4/5 rounded-2xl bg-white sm:h-20" />
          <SkeletonBlock className="mt-7 h-6 w-2/3 rounded-xl bg-white/80" />
          <SkeletonBlock className="mt-3 h-6 w-1/2 rounded-xl bg-white/80" />
        </div>
      </section>
      <section className="mx-auto max-w-6xl px-5 sm:px-6">
        <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
          <div className="md:col-span-2">
            <SkeletonCard className="min-h-[440px] p-6 sm:p-10" />
          </div>
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 md:grid-cols-1">
            <BentoCard className="flex min-h-[160px] flex-col justify-center">
              <SkeletonBlock className="h-12 w-24 rounded-xl bg-[#EFEFF4]" />
              <SkeletonBlock className="mt-4 h-4 w-28 rounded-lg bg-[#EFEFF4]" />
            </BentoCard>
            <BentoCard className="flex min-h-[160px] flex-col justify-center">
              <SkeletonBlock className="h-12 w-20 rounded-xl bg-[#EFEFF4]" />
              <SkeletonBlock className="mt-4 h-4 w-24 rounded-lg bg-[#EFEFF4]" />
            </BentoCard>
          </div>
        </div>
      </section>
      <section className="mx-auto max-w-6xl px-5 py-16 sm:px-6">
        <SkeletonBlock className="h-10 w-48 rounded-xl bg-white" />
        <div className="mt-8 grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <SkeletonCard key={index} />
          ))}
        </div>
      </section>
    </main>
  );
}

export function WeiboPageSkeleton() {
  return (
    <main className="mx-auto max-w-6xl bg-surface px-5 py-16 sm:px-6 lg:py-20">
      <section className="mb-10">
        <div className="flex flex-col gap-8 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-3xl">
            <SkeletonBlock className="h-14 w-80 rounded-2xl bg-white sm:h-16" />
            <SkeletonBlock className="mt-6 h-5 w-full max-w-2xl rounded-xl bg-white/80" />
            <SkeletonBlock className="mt-3 h-5 w-4/5 rounded-xl bg-white/80" />
          </div>
          <BentoCard className="min-w-[160px] px-6 py-5">
            <SkeletonBlock className="h-4 w-20 rounded-lg bg-[#EFEFF4]" />
            <SkeletonBlock className="mt-3 h-10 w-16 rounded-xl bg-[#EFEFF4]" />
          </BentoCard>
        </div>
      </section>
      <div className="mb-10 inline-flex max-w-full gap-2 rounded-full bg-[#E8E8ED] p-1">
        {Array.from({ length: 4 }).map((_, index) => (
          <SkeletonBlock key={index} className="h-10 w-20 bg-white/80" />
        ))}
      </div>
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 9 }).map((_, index) => (
          <SkeletonCard key={index} />
        ))}
      </div>
    </main>
  );
}

export function TopicDetailSkeleton() {
  return (
    <main className="mx-auto max-w-6xl bg-surface px-5 py-12 sm:px-6 lg:py-16">
      <SkeletonBlock className="mb-10 h-5 w-24 rounded-lg bg-white" />
      <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_340px]">
        <article className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <SkeletonBlock className="h-8 w-8 rounded-full bg-white" />
            <SkeletonBlock className="h-8 w-28 bg-white" />
            <SkeletonBlock className="h-8 w-32 bg-[#FFF5E6]" />
          </div>
          <SkeletonBlock className="mt-8 h-14 w-4/5 rounded-2xl bg-white sm:h-16" />
          <SkeletonBlock className="mt-5 h-14 w-2/3 rounded-2xl bg-white/80" />
          <BentoCard className="mt-10 min-h-[360px] p-0">
            <SkeletonBlock className="h-[360px] w-full rounded-2xl bg-[#EFEFF4] sm:rounded-3xl" />
          </BentoCard>
          <div className="mt-10 space-y-5">
            <SkeletonCard className="min-h-[220px]" />
            <SkeletonCard className="min-h-[220px]" />
          </div>
        </article>
        <aside className="lg:sticky lg:top-24 lg:self-start">
          <BentoCard className="p-6 sm:p-7">
            <SkeletonBlock className="h-4 w-24 rounded-lg bg-[#EFEFF4]" />
            <div className="mt-6 space-y-5">
              {Array.from({ length: 5 }).map((_, index) => (
                <div key={index} className="flex items-center justify-between gap-4">
                  <SkeletonBlock className="h-4 w-16 rounded-lg bg-[#EFEFF4]" />
                  <SkeletonBlock className="h-4 w-28 rounded-lg bg-[#EFEFF4]" />
                </div>
              ))}
            </div>
          </BentoCard>
        </aside>
      </div>
    </main>
  );
}

export function AboutPageSkeleton() {
  return (
    <main className="mx-auto max-w-4xl bg-surface px-5 py-20 sm:px-6 lg:py-24">
      <section className="mx-auto max-w-3xl text-center">
        <SkeletonBlock className="mx-auto h-16 w-4/5 rounded-2xl bg-white sm:h-20" />
        <SkeletonBlock className="mx-auto mt-7 h-6 w-3/4 rounded-xl bg-white/80" />
      </section>
      <div className="mt-16 space-y-0">
        {Array.from({ length: 3 }).map((_, index) => (
          <section key={index} className="border-b border-gray-200/50 py-12">
            <SkeletonBlock className="h-10 w-48 rounded-xl bg-white" />
            <SkeletonBlock className="mt-5 h-5 w-full rounded-xl bg-white/80" />
            <SkeletonBlock className="mt-3 h-5 w-4/5 rounded-xl bg-white/80" />
          </section>
        ))}
      </div>
    </main>
  );
}
