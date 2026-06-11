import type { ComponentPropsWithoutRef } from "react";

import { cn } from "@/lib/utils";

type BentoCardProps = ComponentPropsWithoutRef<"div"> & {
  interactive?: boolean;
};

export function BentoCard({ className, interactive = false, ...props }: BentoCardProps) {
  return (
    <div
      className={cn(
        "rounded-2xl bg-white p-5 shadow-apple sm:rounded-[28px] sm:p-8",
        interactive && "transition-all duration-300 ease-out hover:scale-[1.01] hover:shadow-apple-lg",
        className,
      )}
      {...props}
    />
  );
}
