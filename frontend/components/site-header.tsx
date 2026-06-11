import { Activity, ArrowUpRight } from "lucide-react";
import Link from "next/link";

const navItems = [
  { href: "/", label: "首页" },
  { href: "/weibo", label: "微博热搜" },
  { href: "/about", label: "关于" },
];

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 border-b border-zinc-200/80 bg-white/85 backdrop-blur-2xl">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6">
        <Link href="/" className="flex min-w-0 items-center gap-3 font-semibold text-ink">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-ink text-white shadow-sm">
            <Activity className="h-4 w-4" aria-hidden="true" />
          </span>
          <span className="truncate tracking-tight">热点洞察</span>
        </Link>
        <nav className="flex items-center gap-1 rounded-md border border-zinc-200 bg-zinc-50/80 p-1">
          {navItems.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="rounded-md px-3 py-2 text-sm font-medium text-muted transition hover:bg-white hover:text-ink hover:shadow-sm"
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <Link
          href="/weibo"
          className="hidden h-9 items-center gap-2 rounded-md border border-zinc-200 bg-white px-3 text-sm font-semibold text-ink shadow-sm transition hover:border-zinc-400 sm:inline-flex"
        >
          热榜
          <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
        </Link>
      </div>
    </header>
  );
}
