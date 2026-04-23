import { createContext, useCallback, useContext, useReducer, type ReactNode } from "react";
import type { Screen, RegimeData, BasketData, BatchItem, TradePlan } from "../types";

interface WorkflowState {
  screen: Screen;
  homeMarket: string;
  regime: RegimeData | null;
  basket: BasketData | null;
  screeningRunId: string | null;
  batchId: string | null;
  batchResults: Record<string, BatchItem>;
  strategyId: string | null;
  tradePlan: TradePlan | null;
  backtestId: string | null;
}

type Action =
  | { type: "SET_SCREEN"; screen: Screen }
  | { type: "SET_REGIME"; regime: RegimeData }
  | { type: "SET_BASKET"; basket: BasketData }
  | { type: "SET_BATCH_ID"; id: string }
  | { type: "UPDATE_BATCH_RESULT"; ticker: string; item: BatchItem }
  | { type: "SET_STRATEGY_ID"; id: string; plan: TradePlan }
  | { type: "SET_BACKTEST_ID"; id: string };

const initialState: WorkflowState = {
  screen: "market",
  homeMarket: "US",
  regime: null,
  basket: null,
  screeningRunId: null,
  batchId: null,
  batchResults: {},
  strategyId: null,
  tradePlan: null,
  backtestId: null,
};

function reducer(state: WorkflowState, action: Action): WorkflowState {
  switch (action.type) {
    case "SET_SCREEN":
      return { ...state, screen: action.screen };
    case "SET_REGIME":
      return { ...state, regime: action.regime };
    case "SET_BASKET":
      return { ...state, basket: action.basket };
    case "SET_BATCH_ID":
      return { ...state, batchId: action.id, batchResults: {} };
    case "UPDATE_BATCH_RESULT":
      return {
        ...state,
        batchResults: { ...state.batchResults, [action.ticker]: action.item },
      };
    case "SET_STRATEGY_ID":
      return { ...state, strategyId: action.id, tradePlan: action.plan };
    case "SET_BACKTEST_ID":
      return { ...state, backtestId: action.id };
    default:
      return state;
  }
}

interface WorkflowContextValue extends WorkflowState {
  setScreen: (s: Screen) => void;
  setRegime: (r: RegimeData) => void;
  setBasket: (b: BasketData) => void;
  setBatchId: (id: string) => void;
  updateBatchResult: (ticker: string, item: BatchItem) => void;
  setStrategyId: (id: string, plan: TradePlan) => void;
  setBacktestId: (id: string) => void;
}

const WorkflowContext = createContext<WorkflowContextValue | null>(null);

export function WorkflowProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);

  const setScreen = useCallback((screen: Screen) => {
    dispatch({ type: "SET_SCREEN", screen });
  }, []);

  const setRegime = useCallback((regime: RegimeData) => {
    dispatch({ type: "SET_REGIME", regime });
  }, []);

  const setBasket = useCallback((basket: BasketData) => {
    dispatch({ type: "SET_BASKET", basket });
  }, []);

  const setBatchId = useCallback((id: string) => {
    dispatch({ type: "SET_BATCH_ID", id });
  }, []);

  const updateBatchResult = useCallback((ticker: string, item: BatchItem) => {
    dispatch({ type: "UPDATE_BATCH_RESULT", ticker, item });
  }, []);

  const setStrategyId = useCallback((id: string, plan: TradePlan) => {
    dispatch({ type: "SET_STRATEGY_ID", id, plan });
  }, []);

  const setBacktestId = useCallback((id: string) => {
    dispatch({ type: "SET_BACKTEST_ID", id });
  }, []);

  const value: WorkflowContextValue = {
    ...state,
    setScreen,
    setRegime,
    setBasket,
    setBatchId,
    updateBatchResult,
    setStrategyId,
    setBacktestId,
  };

  return (
    <WorkflowContext.Provider value={value}>
      {children}
    </WorkflowContext.Provider>
  );
}

export function useWorkflow(): WorkflowContextValue {
  const ctx = useContext(WorkflowContext);
  if (!ctx) throw new Error("useWorkflow must be used within WorkflowProvider");
  return ctx;
}
