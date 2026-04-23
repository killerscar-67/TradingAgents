export type RunStatus = "pending" | "running" | "completed" | "error";

export interface AnalysisRun {
  run_id: string;
  ticker: string;
  analysis_date: string;
  selected_analysts: string[];
  execution_mode: string;
  llm_provider: string;
  deep_think_llm: string;
  quick_think_llm: string;
  created_at: string;
  status: RunStatus;
  started_at: string | null;
  completed_at: string | null;
  report_sections: Record<string, string>;
  report_paths: Record<string, string>;
  stats: Record<string, unknown>;
  errors: string[];
  final_order_intent: OrderIntent | null;
}

export interface ModelOption {
  label: string;
  value: string;
}

export interface ProviderModelOptions {
  custom: boolean;
  deep: ModelOption[];
  quick: ModelOption[];
}

export interface ModelCatalog {
  providers: Record<string, ProviderModelOptions>;
}

export interface OrderIntent {
  rating: string;
  blocked: boolean;
  source: string;
  execution_mode: string;
  reason: string;
  annotations: Record<string, unknown>;
  symbol: string;
  trade_date: string;
  [key: string]: unknown;
}

export type SseEventType =
  | "status"
  | "agent_status"
  | "report_section"
  | "message"
  | "tool_call"
  | "final_state"
  | "error";

export interface SseEvent {
  type: SseEventType;
  run_id: string;
  sequence: number;
  timestamp: number;
  payload: Record<string, unknown>;
}

export interface AgentStatuses {
  [agent: string]: "pending" | "in_progress" | "completed";
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ConsultantResponse {
  answer: string;
  observations: string[];
  follow_up_questions: string[];
  referenced_context_keys: string[];
  error: string | null;
}
