import { NextRequest } from "next/server";

const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
const IMAGE_CACHE_CONTROL = "public, max-age=86400, s-maxage=604800, stale-while-revalidate=86400";
const FALLBACK_CACHE_CONTROL = "public, max-age=300, s-maxage=300";
const FETCH_TIMEOUT_MS = 10000;

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const target = parseAllowedSinaImageUrl(request.nextUrl.searchParams.get("url"));
  if (!target) {
    return fallbackImageResponse();
  }

  try {
    const response = await fetch(target.toString(), {
      redirect: "follow",
      signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
      headers: {
        Accept: "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        Referer: "https://weibo.com/",
        "User-Agent":
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
      },
    });

    if (!response.ok || !parseAllowedSinaImageUrl(response.url)) {
      return fallbackImageResponse();
    }

    const contentType = response.headers.get("content-type")?.toLowerCase() || "";
    if (!contentType.startsWith("image/")) {
      return fallbackImageResponse();
    }

    const contentLength = Number(response.headers.get("content-length") || 0);
    if (Number.isFinite(contentLength) && contentLength > MAX_IMAGE_BYTES) {
      return fallbackImageResponse();
    }

    const body = await response.arrayBuffer();
    if (body.byteLength > MAX_IMAGE_BYTES) {
      return fallbackImageResponse();
    }

    return new Response(body, {
      headers: {
        "Cache-Control": IMAGE_CACHE_CONTROL,
        "Content-Type": contentType,
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch {
    return fallbackImageResponse();
  }
}

function parseAllowedSinaImageUrl(value: string | null): URL | null {
  if (!value) {
    return null;
  }
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || (url.port && url.port !== "443")) {
      return null;
    }
    if (!isSinaImgHost(url.hostname) || url.username || url.password) {
      return null;
    }
    return url;
  } catch {
    return null;
  }
}

function isSinaImgHost(hostname: string) {
  const normalized = hostname.toLowerCase();
  return normalized === "sinaimg.cn" || normalized.endsWith(".sinaimg.cn");
}

function fallbackImageResponse() {
  return new Response(defaultCoverSvg(), {
    headers: {
      "Cache-Control": FALLBACK_CACHE_CONTROL,
      "Content-Type": "image/svg+xml; charset=utf-8",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

function defaultCoverSvg() {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="675" viewBox="0 0 1200 675" role="img" aria-label="Hot Insight">
  <defs>
    <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0" stop-color="#fff7ed"/>
      <stop offset="0.52" stop-color="#ffffff"/>
      <stop offset="1" stop-color="#fee2e2"/>
    </linearGradient>
    <linearGradient id="line" x1="0" x2="1" y1="0" y2="0">
      <stop offset="0" stop-color="#ef4444"/>
      <stop offset="1" stop-color="#f59e0b"/>
    </linearGradient>
  </defs>
  <rect width="1200" height="675" fill="url(#bg)"/>
  <rect x="86" y="84" width="1028" height="507" rx="34" fill="#ffffff" fill-opacity="0.78" stroke="#f4d7d7"/>
  <path d="M170 420 C270 250 360 355 455 245 S650 330 740 215 S900 255 1030 150" fill="none" stroke="url(#line)" stroke-width="20" stroke-linecap="round"/>
  <circle cx="1030" cy="150" r="34" fill="#ef4444"/>
  <text x="168" y="190" fill="#18181b" font-family="Arial, Helvetica, sans-serif" font-size="58" font-weight="700">HOT INSIGHT</text>
  <text x="170" y="264" fill="#71717a" font-family="Arial, Helvetica, sans-serif" font-size="30">AI-powered trend brief</text>
</svg>`;
}
