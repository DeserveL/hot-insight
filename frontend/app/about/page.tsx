import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "关于",
  description: "热点洞察的数据来源与分析说明。",
};

export default function AboutPage() {
  return (
    <main className="mx-auto max-w-4xl bg-surface px-5 py-20 sm:px-6 lg:py-24">
      <section className="mx-auto max-w-3xl text-center">
        <div className="text-sm font-semibold text-[#9A6A35]">关于</div>
        <h1 className="mt-5 text-balance text-6xl font-semibold leading-none tracking-tight text-[#1D1D1F] sm:text-7xl">
          关于热点洞察
        </h1>
        <p className="mt-7 text-xl leading-relaxed text-[#86868B]">
          这里整理公开热点信息，并用 AI 辅助提炼事件脉络、事实要点和阅读风险。
        </p>
      </section>

      <div className="mt-16">
        <InfoSection title="数据来源">
          热点内容来自公开可访问的信息来源，页面会展示话题标题、热度、排名和更新时间，帮助读者快速了解正在被关注的事件。
        </InfoSection>
        <InfoSection title="AI 辅助说明">
          AI 洞察用于辅助整理公开信息，内容会尽量区分事实、推测和评价，并保留参考来源。无法确认的信息会明确标注。
        </InfoSection>
        <InfoSection title="通知订阅">
          你可以将重点热点同步到企业微信或 Telegram 频道，方便在常用消息工具中及时查看。
        </InfoSection>
      </div>
    </main>
  );
}

function InfoSection({ title, children }: { title: string; children: string }) {
  return (
    <section className="border-b border-gray-200/50 py-12">
      <h2 className="text-3xl font-semibold tracking-tight text-[#1D1D1F] sm:text-4xl">{title}</h2>
      <p className="mt-5 text-lg leading-relaxed text-[#86868B]">{children}</p>
    </section>
  );
}
