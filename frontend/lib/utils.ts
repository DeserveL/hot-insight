import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

const SITE_TIME_ZONE = process.env.NEXT_PUBLIC_SITE_TIME_ZONE || "Asia/Shanghai";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatScore(value: number | null) {
  if (value === null || Number.isNaN(value)) {
    return "-";
  }
  if (value >= 10000) {
    return `${(value / 10000).toFixed(1)}万`;
  }
  return new Intl.NumberFormat("zh-CN").format(value);
}

export function formatDateTime(value: string) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: SITE_TIME_ZONE,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function formatDurationBetween(startValue: string, endValue: string) {
  const start = new Date(startValue);
  const end = new Date(endValue || startValue);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
    return "-";
  }

  const durationMinutes = Math.max(0, Math.round((end.getTime() - start.getTime()) / 60000));
  if (durationMinutes < 1) {
    return "刚刚上榜";
  }
  if (durationMinutes < 60) {
    return `约 ${durationMinutes} 分钟`;
  }

  const durationHours = Math.round(durationMinutes / 60);
  if (durationHours < 24) {
    return `约 ${durationHours} 小时`;
  }

  const durationDays = Math.round(durationHours / 24);
  return `约 ${durationDays} 天`;
}

export function sourceLabel(sourceId: string) {
  if (sourceId === "weibo_official") {
    return "微博官方";
  }
  return sourceId || "-";
}

export function tagTone(tag: string) {
  if (tag === "爆") {
    return "bg-[#FFF1E6] text-[#A55A2A]";
  }
  if (tag === "沸") {
    return "bg-[#F7E8D4] text-[#9A6A35]";
  }
  if (tag === "热") {
    return "bg-[#F8EDC9] text-[#9B7A2F]";
  }
  return "bg-[#ECECF0] text-[#6E6E73]";
}

export function confidenceLabel(value: string) {
  if (value === "high") {
    return "高";
  }
  if (value === "medium") {
    return "中";
  }
  if (value === "low") {
    return "低";
  }
  return value || "未标注";
}
