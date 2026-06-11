import { request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";

import type { Topic, TopicListResponse, TrendsSummary } from "@/lib/types";

const API_BASE_URL = process.env.API_INTERNAL_BASE_URL || "http://127.0.0.1:8000";
const API_TIMEOUT_MS = 15000;

async function apiFetch<T>(path: string): Promise<T> {
  const started = Date.now();
  const url = `${API_BASE_URL}${path}`;
  try {
    const response = await requestJson(url);
    if (response.status < 200 || response.status >= 300) {
      logApiFailure(path, response.status, Date.now() - started);
      throw new Error(`API request failed: ${response.status} ${path}`);
    }
    return response.data as T;
  } catch (error) {
    if (!(error instanceof Error && error.message.startsWith("API request failed:"))) {
      logApiFailure(path, 0, Date.now() - started, error);
    }
    throw error;
  }
}

export function getTopics(params: { tag?: string; limit?: number; cursor?: string } = {}) {
  const search = new URLSearchParams({ channel: "weibo" });
  if (params.tag) {
    search.set("tag", params.tag);
  }
  if (params.limit) {
    search.set("limit", String(params.limit));
  }
  if (params.cursor) {
    search.set("cursor", params.cursor);
  }
  return apiFetch<unknown>(`/api/v1/topics?${search.toString()}`).then(normalizeTopicListResponse);
}

export function getTopic(id: string) {
  return apiFetch<Topic>(`/api/v1/topics/${encodeURIComponent(id)}`);
}

export function getTrendsSummary() {
  return apiFetch<unknown>("/api/v1/trends/summary").then(normalizeTrendsSummary);
}

export function getPublicSiteUrl() {
  return (process.env.PUBLIC_SITE_URL || process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000").replace(
    /\/$/,
    "",
  );
}

function normalizeTopicListResponse(payload: unknown): TopicListResponse {
  const data = isRecord(payload) ? payload : {};
  return {
    items: Array.isArray(data.items) ? (data.items as Topic[]) : [],
    next_cursor: typeof data.next_cursor === "string" ? data.next_cursor : null,
  };
}

function normalizeTrendsSummary(payload: unknown): TrendsSummary {
  const data = isRecord(payload) ? payload : {};
  return {
    channels: Array.isArray(data.channels) ? (data.channels as TrendsSummary["channels"]) : [],
    topic_count: typeof data.topic_count === "number" ? data.topic_count : 0,
    last_seen_at: typeof data.last_seen_at === "string" ? data.last_seen_at : "",
    tags: Array.isArray(data.tags) ? (data.tags as TrendsSummary["tags"]) : [],
    latest_topics: Array.isArray(data.latest_topics) ? (data.latest_topics as Topic[]) : [],
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function requestJson(urlText: string): Promise<{ status: number; data: unknown }> {
  return new Promise((resolve, reject) => {
    const url = new URL(urlText);
    const request = (url.protocol === "https:" ? httpsRequest : httpRequest)(
      url,
      {
        method: "GET",
        headers: {
          Accept: "application/json",
        },
        timeout: API_TIMEOUT_MS,
      },
      (response) => {
        const chunks: Buffer[] = [];
        response.on("data", (chunk: Buffer) => chunks.push(chunk));
        response.on("end", () => {
          const status = response.statusCode || 0;
          const text = Buffer.concat(chunks).toString("utf8");
          if (!text) {
            resolve({ status, data: null });
            return;
          }
          try {
            resolve({ status, data: JSON.parse(text) });
          } catch (error) {
            reject(error);
          }
        });
      },
    );
    request.on("timeout", () => {
      request.destroy(new Error(`API request timeout after ${API_TIMEOUT_MS}ms`));
    });
    request.on("error", reject);
    request.end();
  });
}

function logApiFailure(path: string, status: number, durationMs: number, error?: unknown) {
  const apiHost = safeApiHost(API_BASE_URL);
  const errorMessage = error instanceof Error ? error.message : "";
  console.error(
    `[hot-insight-web] API request failed path=${path} status=${status || "-"} api_host=${apiHost} duration_ms=${durationMs} error=${errorMessage || "-"}`,
  );
}

function safeApiHost(value: string) {
  try {
    const url = new URL(value);
    return url.host;
  } catch {
    return "unknown";
  }
}
