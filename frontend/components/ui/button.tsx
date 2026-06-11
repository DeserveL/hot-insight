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
        "inline-flex h-11 items-center justify-center rounded-full px-5 text-sm font-semibold transition-all duration-300 ease-out hover:scale-[1.01]",
        variant === "primary"
          ? "bg-[#1D1D1F] text-white shadow-apple hover:bg-black hover:shadow-apple-lg"
          : "bg-white text-[#1D1D1F] shadow-apple hover:shadow-apple-lg",
        className,
      )}
      {...props}
    >
      {children}
    </Link>
  );
}
