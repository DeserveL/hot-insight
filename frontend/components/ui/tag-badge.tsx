import { cn, tagTone } from "@/lib/utils";

export function TagBadge({ tag, className }: { tag: string; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-7 min-w-7 items-center justify-center rounded-md border px-2 text-sm font-semibold",
        tagTone(tag),
        className,
      )}
    >
      {tag || "无"}
    </span>
  );
}
