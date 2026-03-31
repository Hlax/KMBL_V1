"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";

const LS_URL = "kmbl_autonomous_url";
const LS_THREAD = "kmbl_autonomous_thread_id";
const LS_IDENTITY = "kmbl_autonomous_identity_id";

type RunResult = {
  time: string;
  graph_run_id?: string;
  status?: string;
  staging_snapshot_id?: string;
  error?: string;
};

export default function AutonomousPage() {
  const [url, setUrl] = useState("");
  const [savedUrl, setSavedUrl] = useState<string | null>(null);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [identityId, setIdentityId] = useState<string | null>(null);
  const threadIdRef = useRef<string | null>(null);
  const identityIdRef = useRef<string | null>(null);
  const [running, setRunning] = useState(false);
  const [runCount, setRunCount] = useState(0);
  const [currentRun, setCurrentRun] = useState<string | null>(null);
  const [runs, setRuns] = useState<RunResult[]>([]);
  const [message, setMessage] = useState("");
  const [messages, setMessages] = useState<string[]>([]);
  const messagesRef = useRef<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const stopRef = useRef(false);
  const runsEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    const stored = localStorage.getItem(LS_URL);
    if (stored) {
      setSavedUrl(stored);
      setUrl(stored);
    }
    const t = localStorage.getItem(LS_THREAD);
    const i = localStorage.getItem(LS_IDENTITY);
    if (t) {
      setThreadId(t);
      threadIdRef.current = t;
    }
    if (i) {
      setIdentityId(i);
      identityIdRef.current = i;
    }
  }, []);

  useEffect(() => {
    runsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [runs]);

  const saveUrl = () => {
    if (!url.trim()) return;
    localStorage.setItem(LS_URL, url.trim());
    setSavedUrl(url.trim());
  };

  const resetSession = () => {
    localStorage.removeItem(LS_THREAD);
    localStorage.removeItem(LS_IDENTITY);
    setThreadId(null);
    setIdentityId(null);
    threadIdRef.current = null;
    identityIdRef.current = null;
  };

  const triggerRun = async (): Promise<RunResult> => {
    const targetUrl = savedUrl || url.trim();
    if (!targetUrl) {
      return { time: new Date().toLocaleTimeString(), error: "No URL set" };
    }

    const instructionSnapshot = [...messagesRef.current];

    try {
      const body: Record<string, unknown> = {
        identity_url: targetUrl,
        trigger_type: "prompt",
        scenario_preset: "identity_url_static_v1",
      };

      // Same thread + identity → orchestrator skips re-scrape; working staging / ratings carry over.
      // Refs: loop must read latest IDs after first run (state alone is stale inside the while loop).
      const tidLoop = threadIdRef.current;
      const iidLoop = identityIdRef.current;
      if (tidLoop && iidLoop) {
        body.thread_id = tidLoop;
        body.identity_id = iidLoop;
      }

      if (instructionSnapshot.length > 0) {
        body.user_instructions = instructionSnapshot.join("\n");
      }

      const res = await fetch("/api/runs/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      const data = await res.json();

      if (!res.ok) {
        let errorMsg = `HTTP ${res.status}`;
        if (typeof data.detail === "string") {
          errorMsg = data.detail;
        } else if (Array.isArray(data.detail)) {
          errorMsg = data.detail.map((e: { msg?: string }) => e.msg || JSON.stringify(e)).join(", ");
        } else if (typeof data.error === "string") {
          errorMsg = data.error;
        } else if (data.detail) {
          errorMsg = JSON.stringify(data.detail);
        }
        return {
          time: new Date().toLocaleTimeString(),
          error: errorMsg,
        };
      }

      const tid = typeof data.thread_id === "string" ? data.thread_id : null;
      const iid = typeof data.identity_id === "string" ? data.identity_id : null;
      if (tid) {
        localStorage.setItem(LS_THREAD, tid);
        setThreadId(tid);
        threadIdRef.current = tid;
      }
      if (iid) {
        localStorage.setItem(LS_IDENTITY, iid);
        setIdentityId(iid);
        identityIdRef.current = iid;
      }

      setCurrentRun(data.graph_run_id);

      let status = "running";
      let stagingId: string | null = null;
      for (let i = 0; i < 120 && status === "running"; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        if (stopRef.current) break;

        try {
          const pollRes = await fetch(`/api/runs/${data.graph_run_id}`);
          const pollData = await pollRes.json();
          // GET /detail nests status under summary; lightweight /runs/{id} has top-level status.
          const s =
            pollData?.summary && typeof pollData.summary === "object"
              ? (pollData.summary as { status?: string }).status
              : pollData.status;
          status = typeof s === "string" ? s : "running";
          stagingId =
            (pollData.associated_outputs as { staging_snapshot_id?: string } | undefined)
              ?.staging_snapshot_id ?? pollData.staging_snapshot_id ?? null;

          if (status === "completed" || status === "failed") break;
        } catch {
          // Keep polling
        }
      }

      if (instructionSnapshot.length > 0) {
        setMessages([]);
      }

      return {
        time: new Date().toLocaleTimeString(),
        graph_run_id: data.graph_run_id,
        status,
        staging_snapshot_id: stagingId ?? undefined,
      };
    } catch (e) {
      return {
        time: new Date().toLocaleTimeString(),
        error: e instanceof Error ? e.message : String(e),
      };
    }
  };

  const startLoop = async () => {
    if (!savedUrl && !url.trim()) {
      setError("Enter a URL first");
      return;
    }
    if (!savedUrl) saveUrl();

    setRunning(true);
    setError(null);
    stopRef.current = false;

    while (!stopRef.current) {
      const result = await triggerRun();
      setRuns((prev) => [...prev.slice(-49), result]);
      setRunCount((c) => c + 1);
      setCurrentRun(null);

      if (stopRef.current) break;

      await new Promise((r) => setTimeout(r, 3000));
    }

    setRunning(false);
  };

  const stopLoop = () => {
    stopRef.current = true;
    setRunning(false);
  };

  const sendMessage = () => {
    if (!message.trim()) return;
    setMessages((prev) => [...prev, message.trim()]);
    setMessage("");
  };

  const clearMessages = () => setMessages([]);

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "1.5rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
        <h1 style={{ margin: 0, fontSize: "1.5rem" }}>Autonomous Runner</h1>
        <Link href="/" style={{ color: "#3498db" }}>← Home</Link>
      </div>

      {error && (
        <div style={{ background: "#5c1a1a", border: "1px solid #e74c3c", padding: "0.75rem", borderRadius: 6, marginBottom: "1rem" }}>
          {error}
        </div>
      )}

      {/* URL Input */}
      <div style={{ background: "#1a1a2e", padding: "1rem", borderRadius: 8, marginBottom: "1rem", border: "1px solid #333" }}>
        <div style={{ display: "flex", gap: "0.5rem", marginBottom: savedUrl ? "0.5rem" : 0 }}>
          <input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://yourwebsite.com"
            style={{
              flex: 1,
              padding: "0.6rem 0.8rem",
              borderRadius: 6,
              border: "1px solid #444",
              background: "#0d0d1a",
              color: "#fff",
              fontSize: "0.95rem",
            }}
          />
          <button
            onClick={saveUrl}
            disabled={!url.trim()}
            style={{
              padding: "0.6rem 1rem",
              borderRadius: 6,
              border: "none",
              background: "#3498db",
              color: "#fff",
              fontWeight: 600,
              cursor: url.trim() ? "pointer" : "not-allowed",
              opacity: url.trim() ? 1 : 0.5,
            }}
          >
            Save
          </button>
        </div>
        {savedUrl && (
          <p style={{ margin: 0, fontSize: "0.85rem", color: "#27ae60" }}>
            Saved: {savedUrl}
          </p>
        )}
        <div style={{ marginTop: "0.75rem", display: "flex", flexWrap: "wrap", gap: "0.75rem", alignItems: "center", fontSize: "0.85rem", color: "#aaa" }}>
          {threadId && identityId ? (
            <span style={{ color: "#2ecc71" }}>
              Loop session: same thread — planner sees working staging & ratings.
            </span>
          ) : (
            <span>First run will fetch the site and start a session; later runs reuse it.</span>
          )}
          <button
            type="button"
            onClick={resetSession}
            style={{
              padding: "0.35rem 0.65rem",
              borderRadius: 6,
              border: "1px solid #666",
              background: "transparent",
              color: "#ccc",
              cursor: "pointer",
              fontSize: "0.8rem",
            }}
          >
            New session (re-fetch identity)
          </button>
        </div>
      </div>

      {/* Controls */}
      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem", alignItems: "center" }}>
        <button
          onClick={startLoop}
          disabled={running || (!savedUrl && !url.trim())}
          style={{
            padding: "0.75rem 1.5rem",
            borderRadius: 6,
            border: "none",
            background: running ? "#1a5c38" : "#27ae60",
            color: "#fff",
            fontWeight: 600,
            fontSize: "1rem",
            cursor: running ? "not-allowed" : "pointer",
          }}
        >
          {running ? "Running..." : "▶ Start"}
        </button>
        <button
          onClick={stopLoop}
          disabled={!running}
          style={{
            padding: "0.75rem 1.5rem",
            borderRadius: 6,
            border: "none",
            background: running ? "#e74c3c" : "#5c1a1a",
            color: "#fff",
            fontWeight: 600,
            fontSize: "1rem",
            cursor: running ? "pointer" : "not-allowed",
          }}
        >
          ■ Stop
        </button>
        <span style={{
          marginLeft: "1rem",
          padding: "0.5rem 1rem",
          borderRadius: 20,
          background: running ? "#27ae60" : "#7f8c8d",
          color: "#fff",
          fontWeight: 600,
          fontSize: "0.9rem",
        }}>
          {running ? "Active" : "Stopped"}
        </span>
        <span style={{ marginLeft: "auto", color: "#888" }}>
          Runs: {runCount}
        </span>
      </div>

      {/* Instructions */}
      <div style={{ background: "#1a1a2e", padding: "1rem", borderRadius: 8, marginBottom: "1rem", border: "1px solid #333" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
          <h3 style={{ margin: 0, fontSize: "1rem" }}>Instructions for Planner</h3>
          {messages.length > 0 && (
            <button onClick={clearMessages} style={{ background: "none", border: "none", color: "#888", cursor: "pointer", fontSize: "0.85rem" }}>
              Clear
            </button>
          )}
        </div>
        <p style={{ margin: "0 0 0.75rem", fontSize: "0.85rem", color: "#888" }}>
          Sent once per run, then cleared (add again for the next iteration)
        </p>
        {messages.length > 0 && (
          <div style={{ marginBottom: "0.75rem" }}>
            {messages.map((m, i) => (
              <div key={i} style={{ background: "#3498db", padding: "0.5rem 0.75rem", borderRadius: 6, marginBottom: "0.25rem", fontSize: "0.9rem" }}>
                {m}
              </div>
            ))}
          </div>
        )}
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <input
            type="text"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && sendMessage()}
            placeholder="e.g. 'Make it more minimal' or 'Use warmer colors'"
            style={{
              flex: 1,
              padding: "0.6rem 0.8rem",
              borderRadius: 6,
              border: "1px solid #444",
              background: "#0d0d1a",
              color: "#fff",
              fontSize: "0.9rem",
            }}
          />
          <button
            onClick={sendMessage}
            disabled={!message.trim()}
            style={{
              padding: "0.6rem 1rem",
              borderRadius: 6,
              border: "none",
              background: "#f39c12",
              color: "#fff",
              fontWeight: 600,
              cursor: message.trim() ? "pointer" : "not-allowed",
              opacity: message.trim() ? 1 : 0.5,
            }}
          >
            Add
          </button>
        </div>
      </div>

      {/* Run Log */}
      <div style={{ background: "#1a1a2e", padding: "1rem", borderRadius: 8, border: "1px solid #333" }}>
        <h3 style={{ margin: "0 0 0.75rem", fontSize: "1rem" }}>Run Log</h3>
        <div style={{
          maxHeight: 300,
          overflowY: "auto",
          fontFamily: "monospace",
          fontSize: "0.85rem",
          background: "rgba(0,0,0,0.3)",
          borderRadius: 4,
          padding: "0.5rem",
        }}>
          {currentRun && (
            <div style={{ padding: "0.5rem 0", borderBottom: "1px solid #333", color: "#f39c12" }}>
              Running: {currentRun.slice(0, 8)}...
            </div>
          )}
          {runs.length === 0 && !currentRun && (
            <p style={{ color: "#888", margin: 0 }}>No runs yet. Click Start to begin.</p>
          )}
          {runs.map((r, i) => (
            <div key={i} style={{ padding: "0.5rem 0", borderBottom: "1px solid rgba(255,255,255,0.05)" }}>
              <span style={{ color: "#888" }}>{r.time}</span>
              {" "}
              {r.error ? (
                <span style={{ color: "#e74c3c" }}>{r.error}</span>
              ) : (
                <>
                  <span style={{ color: r.status === "completed" ? "#27ae60" : "#f39c12" }}>
                    {r.status}
                  </span>
                  {r.staging_snapshot_id && (
                    <>
                      {" → "}
                      <Link href={`/review/staging/${r.staging_snapshot_id}`} style={{ color: "#3498db" }}>
                        View staging
                      </Link>
                    </>
                  )}
                </>
              )}
            </div>
          ))}
          <div ref={runsEndRef} />
        </div>
      </div>
    </div>
  );
}
