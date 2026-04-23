import { useState } from "react";
import { RunForm } from "./components/RunForm";
import { RunDetail } from "./components/RunDetail";
import { ReportArchives } from "./components/ReportArchives";

export default function App() {
  const [runId, setRunId] = useState<string | null>(null);
  const [view, setView] = useState<"new" | "archives">("new");

  if (runId) {
    return <RunDetail runId={runId} onBack={() => {
      setRunId(null);
      setView("new");
    }} />;
  }

  if (view === "archives") {
    return (
      <ReportArchives
        onOpenRun={setRunId}
        onNewAnalysis={() => setView("new")}
      />
    );
  }

  return <RunForm onRunCreated={setRunId} onViewArchives={() => setView("archives")} />;
}
