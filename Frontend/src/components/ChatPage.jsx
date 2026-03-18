import { useState, useEffect, useRef } from "react";
import ChatMessage from "./ChatMessage";
import ChatInput from "./ChatInput";
import { createSession, sendMessage, getSession } from "../services/api";

const SESSION_KEY = "ezreport_session_id";

export default function ChatPage() {
  const [sessionId, setSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef(null);

  // Scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // On mount, try to restore session
  useEffect(() => {
    const stored = sessionStorage.getItem(SESSION_KEY);
    if (stored) {
      setSessionId(stored);
      // Reload messages from backend
      getSession(stored)
        .then((data) => setMessages(data.messages || []))
        .catch(() => {
          // Session expired / invalid — clear it
          sessionStorage.removeItem(SESSION_KEY);
        });
    }
  }, []);

  const ensureSession = async () => {
    if (sessionId) return sessionId;
    const { session_id } = await createSession();
    setSessionId(session_id);
    sessionStorage.setItem(SESSION_KEY, session_id);
    return session_id;
  };

  const handleSend = async (text) => {
    if (loading) return; // prevent duplicate rapid sends

    // Optimistically add user message
    const userMsg = { role: "user", content: text, timestamp: new Date().toISOString() };
    setMessages((prev) => [...prev, userMsg]);
    setLoading(true);

    try {
      const sid = await ensureSession();
      const { reply } = await sendMessage(sid, text);
      setMessages((prev) => [...prev, reply]);
    } catch (err) {
      // Add inline error
      setMessages((prev) => [
        ...prev,
        {
          role: "error",
          content: err.message || "Something went wrong. Please try again.",
          timestamp: new Date().toISOString(),
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="chat-page">
      {/* Header */}
      <header className="chat-header">
        <div className="header-left">
          <div className="logo-icon">
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
            </svg>
          </div>
          <div>
            <h1 className="header-title">EzReport</h1>
            <p className="header-subtitle">Ask questions about your data in plain English</p>
          </div>
        </div>
        <div className="header-right">
          <span className="status-dot" />
          <span className="status-text">Connected</span>
        </div>
      </header>

      {/* Messages */}
      <main className="chat-messages">
        {messages.length === 0 && (
          <div className="empty-state">
            <div className="empty-icon">💬</div>
            <h2>Welcome to EzReport</h2>
            <p>Ask anything about your dataset. For example:</p>
            <div className="example-queries">
              <button className="example-btn" onClick={() => handleSend("Show me total revenue by region")}>
                Show me total revenue by region
              </button>
              <button className="example-btn" onClick={() => handleSend("What is the average ROI?")}>
                What is the average ROI?
              </button>
              <button className="example-btn" onClick={() => handleSend("Top 5 campaigns by revenue")}>
                Top 5 campaigns by revenue
              </button>
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <ChatMessage key={i} msg={msg} />
        ))}

        {/* Typing indicator */}
        {loading && (
          <div className="msg-row msg-row--assistant">
            <div className="bubble bubble--typing">
              <span className="dot" />
              <span className="dot" />
              <span className="dot" />
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </main>

      {/* Input */}
      <ChatInput onSend={handleSend} disabled={loading} />
    </div>
  );
}
