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

// --- Phase 12: workflow screens ---

export type Screen =
  | "market"
  | "screen"
  | "batch"
  | "strategy"
  | "backtest"
  | "history"
  | "settings";

export interface RegimeData {
  home_market?: string;
  label: string;
  confidence: number;
  suggested_entry_mode: string;
  event_risk_flag: boolean;
  inputs?: Record<string, unknown>;
}

export interface BreadthData {
  pct_above_50d: number;
  pct_above_200d: number;
  new_highs_minus_lows: number;
  advance_decline_ratio: number;
  mcclellan_oscillator: number;
  headline: string;
}

export interface IndexTile {
  symbol: string;
  label: string;
  price: number;
  change_pct: number;
}

export interface SectorTile {
  symbol: string;
  label?: string;
  change_pct: number;
}

export interface MarketCalendarEvent {
  date: string;
  name: string;
  impact: string;
}

export interface MarketOverview {
  home_market?: string;
  trade_date?: string;
  regime: RegimeData;
  indices: IndexTile[];
  breadth: BreadthData;
  sectors?: SectorTile[];
  events?: MarketCalendarEvent[];
  status: string;
}

export interface ScreeningResult {
  symbol: string;
  score: number;
  regime_label: string;
  entry_mode: string;
  status: string;
}

export interface BasketData {
  screening_run_id: string;
  symbols: string[];
  regime: RegimeData | null;
  created_at: string;
  status: string;
}

export interface BatchItem {
  ticker: string;
  run_id: string | null;
  status: "queued" | "running" | "completed" | "error";
  rating: string | null;
  error: string | null;
}

export interface TradeEntry {
  ticker: string;
  side: "buy" | "sell";
  quantity: number;
  direction: "LONG" | "SHORT";
  entry: number;
  stop: number;
  target: number;
  size_pct: number;
  rating: string;
  run_id: string;
}

export interface ExposureSummary {
  gross: number;
  net: number;
  long_count: number;
  short_count: number;
}

export interface TradePlan {
  batch_id: string;
  date: string;
  entries: TradeEntry[];
  exposure: ExposureSummary;
  status: string;
}

export interface BacktestKpi {
  total_return_pct: number;
  sharpe: number;
  max_drawdown_pct: number;
  win_rate_pct: number;
  num_trades: number;
  cagr_pct?: number;
  sortino?: number;
  profit_factor?: number;
  avg_hold_bars?: number;
}

export interface TradeLogEntry {
  date: string;
  ticker: string;
  direction: string;
  entry: number;
  exit: number | null;
  pnl_pct: number | null;
  status: string;
  bars?: number;
}

export interface BacktestRun {
  backtest_id: string;
  strategy_id: string;
  start_date: string;
  end_date: string;
  execution_mode: "quant_strict";
  status: "queued" | "running" | "completed" | "error";
  kpi: BacktestKpi | null;
  trade_log: TradeLogEntry[];
  equity_curve: Array<{ time: number; value: number }>;
}

export interface AppSettings {
  llm_provider: string;
  deep_think_llm: string;
  quick_think_llm: string;
  execution_mode: string;
  home_market: string;
  max_debate_rounds: number;
  max_risk_discuss_rounds: number;
  output_language: string;
  top_n?: number;
  score_floor?: number;
  risk_per_trade_pct?: number;
  portfolio_size?: number;
  allow_shorts?: boolean;
  futu_host?: string;
  futu_port?: number;
  status: string;
}

export interface WorkflowSession {
  session_id: string;
  started_at: string;
  screens_visited: Screen[];
  status: string;
}

export interface HistoryItem {
  id: string;
  type: string;
  title: string;
  status: string;
  created_at: string | null;
  completed_at: string | null;
  home_market: string | null;
  workflow_session_id: string | null;
  summary?: string | null;
}
