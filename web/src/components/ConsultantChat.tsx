import { useRef, useState } from "react";
import type { ChatMessage, ConsultantResponse } from "../types";
import styles from "./ConsultantChat.module.css";

interface Props {
  runId: string;
  disabled: boolean;
}

export function ConsultantChat({ runId, disabled }: Props) {
  const [history, setHistory] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const send = async () => {
    if (!input.trim() || loading) return;
    const userMsg = input.trim();
    setInput("");
    setError(null);
    setHistory((h) => [...h, { role: "user", content: userMsg }]);
    setLoading(true);
    try {
      const resp = await fetch(`/api/analysis/${runId}/consultant/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: userMsg, history }),
      });
      if (!resp.ok) {
        const body = await resp.json();
        throw new Error(body.detail ?? `HTTP ${resp.status}`);
      }
      const data: ConsultantResponse = await resp.json();
      if (data.error) {
        setError(data.error);
        return;
      }
      const parts = [data.answer];
      if (data.observations.length > 0) {
        parts.push("Observations:\n" + data.observations.map((o) => `• ${o}`).join("\n"));
      }
      if (data.follow_up_questions.length > 0) {
        parts.push("You might also ask:\n" + data.follow_up_questions.map((q) => `• ${q}`).join("\n"));
      }
      setHistory((h) => [...h, { role: "assistant", content: parts.join("\n\n") }]);
      setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={styles.wrap}>
      <div className={styles.header}>
        <p className={styles.title}>Ask the consultant</p>
      </div>

      {disabled ? (
        <p className={styles.idle}>
          Available once the analysis has enough context. Keep this panel open — it will activate as the run progresses.
        </p>
      ) : (
        <>
          <div className={styles.history}>
            {history.length === 0 && (
              <p className={styles.idle} style={{ padding: 0 }}>
                Ask anything about this analysis — why a rating was given, what risks to watch, how the debate unfolded.
              </p>
            )}
            {history.map((msg, i) => (
              <div key={i} className={msg.role === "user" ? styles.msgUser : styles.msgAssistant}>
                <span className={styles.role}>{msg.role === "user" ? "You" : "Consultant"}</span>
                <pre className={styles.bubble}>{msg.content}</pre>
              </div>
            ))}
            {loading && <p className={styles.thinking}>Thinking…</p>}
            {error && <p className={styles.errorMsg}>{error}</p>}
            <div ref={bottomRef} />
          </div>

          <div className={styles.inputRow}>
            <textarea
              className={styles.input}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              placeholder="Ask about this analysis…"
              disabled={loading}
              rows={2}
            />
            <button
              className={styles.sendBtn}
              onClick={send}
              disabled={loading || !input.trim()}
            >
              Send
            </button>
          </div>
        </>
      )}
    </div>
  );
}
