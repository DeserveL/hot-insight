export type AIDetailSource = {
  title: string;
  url: string;
};

export type AIDetail = {
  summary: string;
  takeaway: string;
  facts: string[];
  commentary: string;
  risk_note: string;
  sources: AIDetailSource[];
  confidence: string;
};

export type Topic = {
  id: string;
  channel_id: string;
  title: string;
  title_key: string;
  tag: string;
  peak_tag: string;
  url: string;
  source_excerpt: string;
  cover_image_url: string;
  source_id: string;
  occurrence_started_at: string;
  recurrence_window_hours: number;
  first_seen_at: string;
  last_seen_at: string;
  rank: number | null;
  best_rank: number | null;
  score: number | null;
  peak_score: number | null;
  seen_count: number;
  ai_status: string;
  ai_error: string;
  ai_detail: AIDetail | null;
  observations?: TopicObservation[];
};

export type TopicObservation = {
  observed_at: string;
  source_id: string;
  rank: number | null;
  score: number | null;
  tag: string;
  url: string;
};

export type TopicListResponse = {
  items: Topic[];
  next_cursor: string | null;
};

export type TrendsSummary = {
  channels: { id: string; name: string; enabled: boolean }[];
  topic_count: number;
  last_seen_at: string;
  tags: { tag: string; count: number }[];
  latest_topics: Topic[];
};
