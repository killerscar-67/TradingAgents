import { WorkflowProvider, useWorkflow } from "./contexts/WorkflowContext";
import { AppShell } from "./components/AppShell";
import { MarketScreen } from "./screens/MarketScreen";
import { ScreeningScreen } from "./screens/ScreeningScreen";
import { BatchScreen } from "./screens/BatchScreen";
import { StrategyScreen } from "./screens/StrategyScreen";
import { BacktestScreen } from "./screens/BacktestScreen";
import { HistoryScreen } from "./screens/HistoryScreen";
import { SettingsScreen } from "./screens/SettingsScreen";

function ScreenRouter() {
  const { screen } = useWorkflow();
  switch (screen) {
    case "market":    return <MarketScreen />;
    case "screen":    return <ScreeningScreen />;
    case "batch":     return <BatchScreen />;
    case "strategy":  return <StrategyScreen />;
    case "backtest":  return <BacktestScreen />;
    case "history":   return <HistoryScreen />;
    case "settings":  return <SettingsScreen />;
  }
}

export default function App() {
  return (
    <WorkflowProvider>
      <AppShell>
        <ScreenRouter />
      </AppShell>
    </WorkflowProvider>
  );
}
