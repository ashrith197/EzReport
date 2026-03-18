import { useState } from "react";

const CHART_COLORS = {
  bar: "#6366f1",
  line: "#22d3ee",
  pie: "#f472b6",
  table: "#a78bfa",
  metric: "#34d399",
  none: "#94a3b8",
};

export default function ChatMessage({ msg }) {
  const [sqlOpen, setSqlOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  if (msg.role === "user") {
    return (
      <div className="msg-row msg-row--user">
        <div className="bubble bubble--user">{msg.content}</div>
      </div>
    );
  }

  // error message
  if (msg.role === "error") {
    return (
      <div className="msg-row msg-row--assistant">
        <div className="bubble bubble--error">
          <span className="error-icon">⚠</span>
          {msg.content}
        </div>
      </div>
    );
  }

  // assistant message
  const { data } = msg;

  const handleCopy = () => {
    if (data?.sql_query) {
      navigator.clipboard.writeText(data.sql_query);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  };

  const chartColor = CHART_COLORS[data?.chart_type] || CHART_COLORS.none;

  return (
    <div className="msg-row msg-row--assistant">
      <div className="bubble bubble--assistant">
        {/* Explanation */}
        <p className="assistant-text">{msg.content}</p>

        {data && (
          <div className="assistant-meta">
            {/* Description */}
            {data.description && (
              <div className="meta-section">
                <span className="meta-label">Description</span>
                <p className="meta-value">{data.description}</p>
              </div>
            )}

            {/* Chart Type Badge */}
            {data.chart_type && (
              <div className="meta-section meta-section--inline">
                <span className="meta-label">Chart Type</span>
                <span
                  className="chart-badge"
                  style={{ "--badge-color": chartColor }}
                >
                  {data.chart_type}
                </span>
              </div>
            )}

            {/* SQL Block */}
            {data.sql_query && (
              <div className="meta-section">
                <div className="sql-header">
                  <button
                    className="sql-toggle"
                    onClick={() => setSqlOpen((p) => !p)}
                  >
                    <span className={`sql-arrow ${sqlOpen ? "open" : ""}`}>
                      ▶
                    </span>
                    SQL Query
                  </button>
                  <button className="copy-btn" onClick={handleCopy}>
                    {copied ? "✓ Copied" : "Copy"}
                  </button>
                </div>
                {sqlOpen && (
                  <pre className="sql-block">
                    <code>{data.sql_query}</code>
                  </pre>
                )}
              </div>
            )}

            {/* Warning */}
            {data.warning && (
              <div className="meta-section meta-section--warning">
                <span className="meta-label">⚠ Warning</span>
                <p className="meta-value">{data.warning}</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
