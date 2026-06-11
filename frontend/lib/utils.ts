import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

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
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function sourceLabel(sourceId: string) {
  if (sourceId === "weibo_official") {
    return "微博官方";
  }
  return sourceId || "-";
}

export function tagTone(tag: string) {
  if (tag === "爆") {
    return "border-red-200 bg-red-50 text-red-700";
  }
  if (tag === "沸") {
    return "border-orange-200 bg-orange-50 text-orange-700";
  }
  if (tag === "热") {
    return "border-amber-200 bg-amber-50 text-amber-700";
  }
  return "border-zinc-200 bg-white text-zinc-600";
}
