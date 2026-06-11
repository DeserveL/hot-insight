import Link from "next/link";
import type { ComponentPropsWithoutRef, ReactNode } from "react";

import { cn } from "@/lib/utils";

type ButtonLinkProps = ComponentPropsWithoutRef<typeof Link> & {
  children: ReactNode;
  variant?: "primary" | "secondary";
};

export function ButtonLink({ children, className, variant = "primary", ...props }: ButtonLinkProps) {
  return (
    <Link
      className={cn(
        "inline-flex h-11 items-center justify-center rounded-md px-5 text-sm font-semibold transition",
        variant === "primary"
          ? "bg-ink text-white shadow-sm hover:bg-black"
          : "border border-zinc-200 bg-white text-ink shadow-sm hover:border-zinc-400",
        className,
      )}
      {...props}
    >
      {children}
    </Link>
  );
}
