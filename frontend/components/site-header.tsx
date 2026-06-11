import { ArrowUpRight, Sparkles } from "lucide-react";
import Link from "next/link";

const navItems = [
  { href: "/", label: "首页" },
  { href: "/weibo", label: "微博热搜" },
  { href: "/about", label: "关于" },
];

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 bg-white/70 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-5 sm:px-6">
        <Link href="/" className="flex min-w-0 items-center gap-2.5 font-semibold text-[#1D1D1F]">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#1D1D1F] text-white shadow-apple">
            <Sparkles className="h-4 w-4" aria-hidden="true" />
          </span>
          <span className="truncate tracking-tight">热点洞察</span>
        </Link>
        <nav className="hidden items-center gap-8 text-sm font-medium text-[#86868B] md:flex">
          {navItems.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="transition-colors duration-300 ease-out hover:text-[#1D1D1F]"
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <Link
          href="/weibo"
          className="hidden h-9 items-center gap-2 rounded-full bg-[#1D1D1F] px-4 text-sm font-semibold text-white shadow-apple transition-all duration-300 ease-out hover:scale-[1.01] hover:bg-black hover:shadow-apple-lg sm:inline-flex"
        >
          热榜
          <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
        </Link>
      </div>
    </header>
  );
}
