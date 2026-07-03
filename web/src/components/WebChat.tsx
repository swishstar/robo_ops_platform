import { useState } from "react";
import { api } from "../api/client";

interface Props {
  visitId?: string;
}

export function WebChat({ visitId }: Props) {
  const [messages, setMessages] = useState<Array<{ role: "user" | "agent"; text: string }>>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [sessionId] = useState(() => `web:${Date.now()}`);

  async function send() {
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", text }]);
    setLoading(true);
    try {
      const res = await api.webChat({ message: text, visit_id: visitId, session_id: sessionId });
      setMessages((m) => [...m, { role: "agent", text: res.reply }]);
    } catch (err) {
      setMessages((m) => [
        ...m,
        { role: "agent", text: err instanceof Error ? err.message : "Request failed." },
      ]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="web-chat">
      <h3>Web Chat</h3>
      <p className="hint">Ask about SOPs, visit data, or say &quot;clock in&quot; / &quot;clock out&quot;.</p>
      <div className="messages">
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            {m.text}
          </div>
        ))}
      </div>
      <div className="chat-input">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="Ask a question or send a command…"
          disabled={loading}
        />
        <button type="button" onClick={send} disabled={loading}>
          Send
        </button>
      </div>
    </div>
  );
}
