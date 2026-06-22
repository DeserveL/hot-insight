"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const FALLBACK_HIDE_MS = 12000;
const MIN_VISIBLE_MS = 220;

export function NavigationProgress() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const routeKey = useMemo(() => `${pathname}?${searchParams.toString()}`, [pathname, searchParams]);
  const previousRouteKey = useRef(routeKey);
  const startedAt = useRef(0);
  const fallbackTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [visible, setVisible] = useState(false);

  const clearTimers = useCallback(() => {
    if (fallbackTimer.current) {
      clearTimeout(fallbackTimer.current);
      fallbackTimer.current = null;
    }
    if (hideTimer.current) {
      clearTimeout(hideTimer.current);
      hideTimer.current = null;
    }
  }, []);

  const showProgress = useCallback(() => {
    clearTimers();
    startedAt.current = Date.now();
    setVisible(true);
    fallbackTimer.current = setTimeout(() => {
      setVisible(false);
      fallbackTimer.current = null;
    }, FALLBACK_HIDE_MS);
  }, [clearTimers]);

  const hideProgress = useCallback(() => {
    if (!startedAt.current) {
      setVisible(false);
      return;
    }
    if (fallbackTimer.current) {
      clearTimeout(fallbackTimer.current);
      fallbackTimer.current = null;
    }
    const elapsed = Date.now() - startedAt.current;
    const delay = Math.max(MIN_VISIBLE_MS - elapsed, 0);
    if (hideTimer.current) {
      clearTimeout(hideTimer.current);
    }
    hideTimer.current = setTimeout(() => {
      setVisible(false);
      hideTimer.current = null;
      startedAt.current = 0;
    }, delay);
  }, []);

  useEffect(() => {
    if (previousRouteKey.current !== routeKey) {
      previousRouteKey.current = routeKey;
      hideProgress();
    }
  }, [hideProgress, routeKey]);

  useEffect(() => {
    function onClick(event: MouseEvent) {
      if (shouldIgnoreClick(event)) {
        return;
      }
      const anchor = closestAnchor(event.target);
      if (!anchor || shouldIgnoreAnchor(anchor)) {
        return;
      }
      const nextUrl = toUrl(anchor.href);
      if (!nextUrl || nextUrl.origin !== window.location.origin || isSamePageOrHashOnly(nextUrl)) {
        return;
      }
      showProgress();
    }

    function onPopState() {
      showProgress();
    }

    document.addEventListener("click", onClick, true);
    window.addEventListener("popstate", onPopState);
    return () => {
      document.removeEventListener("click", onClick, true);
      window.removeEventListener("popstate", onPopState);
      clearTimers();
    };
  }, [clearTimers, showProgress]);

  return (
    <div
      aria-hidden="true"
      className={`pointer-events-none fixed left-0 top-0 z-[100] h-0.5 w-full overflow-hidden bg-transparent transition-opacity duration-200 ${
        visible ? "opacity-100" : "opacity-0"
      }`}
    >
      <div className="h-full w-1/2 origin-left animate-navigation-progress rounded-r-full bg-[#0066CC] shadow-[0_0_12px_rgba(0,102,204,0.35)] motion-reduce:animate-none motion-reduce:w-full" />
    </div>
  );
}

function shouldIgnoreClick(event: MouseEvent) {
  return (
    event.defaultPrevented ||
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  );
}

function closestAnchor(target: EventTarget | null) {
  return target instanceof Element ? target.closest("a") : null;
}

function shouldIgnoreAnchor(anchor: HTMLAnchorElement) {
  const target = anchor.getAttribute("target");
  return (
    Boolean(anchor.getAttribute("download")) ||
    (target !== null && target !== "" && target.toLowerCase() !== "_self")
  );
}

function toUrl(value: string) {
  try {
    return new URL(value, window.location.href);
  } catch {
    return null;
  }
}

function isSamePageOrHashOnly(nextUrl: URL) {
  return nextUrl.pathname === window.location.pathname && nextUrl.search === window.location.search;
}
