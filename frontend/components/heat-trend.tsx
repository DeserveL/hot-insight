import type { TopicObservation } from "@/lib/types";

export function HeatTrend({ observations }: { observations: TopicObservation[] }) {
  const points = observations
    .slice()
    .reverse()
    .map((item) => item.score)
    .filter((value): value is number => typeof value === "number" && !Number.isNaN(value))
    .slice(-20);

  if (points.length < 2) {
    return null;
  }

  const width = 180;
  const height = 48;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = Math.max(max - min, 1);
  const path = points
    .map((value, index) => {
      const x = (index / Math.max(points.length - 1, 1)) * width;
      const y = height - ((value - min) / range) * (height - 8) - 4;
      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");

  return (
    <div className="rounded-2xl bg-white px-4 py-3 shadow-apple">
      <div className="mb-2 text-xs font-bold uppercase tracking-widest text-[#A1A1A6]">热度趋势</div>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-12 w-full text-[#C7B299]" aria-hidden="true">
        <path d={path} fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" />
      </svg>
    </div>
  );
}
