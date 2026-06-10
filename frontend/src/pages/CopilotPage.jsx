import { useState, useEffect, useRef } from "react";
import { useApi, API } from "../hooks/useApi";

export function CopilotPage() {
  const INITIAL_GREETING = [
    {
      role: "assistant",
      thinking: "Tôi đã sẵn sàng hỗ trợ bạn. Hệ thống AI Copilot kết nối dữ liệu SQL Server, bộ tối ưu hóa doanh thu Scipy và tin tức RAG thị trường để đưa ra đề xuất định giá chính xác nhất.",
      text: "Xin chào! Tôi là **Vietjet AI Revenue Copilot** của bạn. Hãy gửi cho tôi yêu cầu định giá hoặc tối ưu hóa cho bất kỳ chuyến bay hay chặng bay nào (ví dụ: *'Tối ưu hóa doanh thu chuyến bay VJ100'* hoặc *'Phân tích chặng SGN-HAN'*).",
      tools: [],
      action: null
    }
  ];

  const [sessions, setSessions] = useState([]);
  const [currentSessionId, setCurrentSessionId] = useState(null);
  const [messages, setMessages] = useState(INITIAL_GREETING);
  const [inputValue, setInputValue] = useState("");
  const [loading, setLoading] = useState(false);
  const [statusData, setStatusData] = useState({ vllm_connected: false, vllm_model: "offline" });
  const [toast, setToast] = useState(null);
  const messagesEndRef = useRef(null);

  // Poll status endpoint to check vLLM connection status
  useEffect(() => {
    fetch(`${API}/agent/status`)
      .then(res => res.json())
      .then(data => setStatusData(data))
      .catch(() => setStatusData({ vllm_connected: false, vllm_model: "offline" }));
  }, []);

  // Fetch all chat sessions on mount
  useEffect(() => {
    fetchSessions();
  }, []);

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  // Handle toast timeout
  useEffect(() => {
    if (toast) {
      const timer = setTimeout(() => setToast(null), 3000);
      return () => clearTimeout(timer);
    }
  }, [toast]);

  const fetchSessions = async (selectLatest = false) => {
    try {
      const response = await fetch(`${API}/agent/sessions`);
      if (response.ok) {
        const data = await response.json();
        setSessions(data);
        if (selectLatest && data.length > 0) {
          handleSelectSession(data[0].id);
        } else if (data.length > 0 && currentSessionId === null) {
          // If first load and there are sessions, auto-select the most recent one
          handleSelectSession(data[0].id);
        }
      }
    } catch (err) {
      console.error("Failed to fetch sessions", err);
    }
  };

  const handleSelectSession = async (sessionId) => {
    setCurrentSessionId(sessionId);
    setLoading(true);
    try {
      const response = await fetch(`${API}/agent/sessions/${sessionId}/messages`);
      if (response.ok) {
        const data = await response.json();
        if (data.length === 0) {
          setMessages(INITIAL_GREETING);
        } else {
          setMessages(
            data.map((m) => ({
              role: m.role,
              thinking: m.thinking,
              text: m.content,
              tools: m.tools_called || [],
              action: m.action
            }))
          );
        }
      }
    } catch (err) {
      setToast({ message: "Không thể tải lịch sử cuộc trò chuyện.", type: "error" });
    } finally {
      setLoading(false);
    }
  };

  const handleNewChat = () => {
    setCurrentSessionId(null);
    setMessages(INITIAL_GREETING);
  };

  const handleDeleteSession = async (e, sessionId) => {
    e.stopPropagation(); // Avoid selecting the session when clicking delete
    if (!window.confirm("Bạn có chắc chắn muốn xóa cuộc trò chuyện này?")) return;

    try {
      const response = await fetch(`${API}/agent/sessions/${sessionId}`, {
        method: "DELETE"
      });
      if (response.ok) {
        setToast({ message: "Đã xóa cuộc trò chuyện thành công.", type: "success" });
        if (currentSessionId === sessionId) {
          handleNewChat();
        }
        fetchSessions();
      }
    } catch (err) {
      setToast({ message: "Không thể xóa cuộc trò chuyện.", type: "error" });
    }
  };

  const handleSend = async (textToSend) => {
    const text = textToSend || inputValue;
    if (!text.trim()) return;

    if (!textToSend) setInputValue("");
    
    // Add user message to UI state temporarily
    setMessages(prev => [...prev, { role: "user", text }]);
    setLoading(true);

    try {
      const response = await fetch(`${API}/agent/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: text,
          session_id: currentSessionId
        })
      });

      if (!response.ok) throw new Error("API error");

      const data = await response.json();
      
      // Update message list
      setMessages(prev => [...prev, {
        role: "assistant",
        thinking: data.thinking,
        text: data.message,
        tools: data.tools_called || [],
        action: data.action || null
      }]);

      // If it was a new chat, update session state and reload list
      if (!currentSessionId) {
        setCurrentSessionId(data.session_id);
        fetchSessions(true);
      } else {
        // Just refresh the sessions list to show updated timestamp
        fetchSessions();
      }
    } catch (err) {
      setMessages(prev => [...prev, {
        role: "assistant",
        text: "Đã xảy ra lỗi khi xử lý yêu cầu. Vui lòng kiểm tra kết nối với server backend và cụm vLLM.",
        tools: []
      }]);
    } finally {
      setLoading(false);
    }
  };

  const handleApplyPrice = async (action, index) => {
    try {
      const response = await fetch(`${API}/flights/${action.flight_id}/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          applied_price: action.recommended_price,
          model_used: `AI Copilot (${statusData.vllm_model})`
        })
      });

      if (!response.ok) throw new Error("Failed to apply");

      // Mark this action as applied in state (non-mutating)
      setMessages(prev => prev.map((msg, idx) => {
        if (idx === index) {
          return {
            ...msg,
            action: { ...msg.action, applied: true }
          };
        }
        return msg;
      }));

      setToast({
        message: `Đã áp dụng thành công mức giá ${action.recommended_price.toLocaleString()} VND cho chuyến bay ${action.flight_no}!`,
        type: "success"
      });
    } catch (err) {
      setToast({
        message: "Có lỗi xảy ra khi áp dụng giá vé.",
        type: "error"
      });
    }
  };

  const suggestions = [
    "Tối ưu hóa doanh thu chuyến bay VJ100",
    "Phân tích chiến lược định giá chặng SGN-HAN",
    "Kiểm tra tác động bối cảnh thị trường chặng bay DAD"
  ];

  return (
    <div style={{
      display: "flex",
      height: "100%",
      width: "100%",
      background: "transparent"
    }}>
      {/* SIDEBAR: Chat History List */}
      <div className="glass-panel" style={{
        width: 280,
        display: "flex",
        flexDirection: "column",
        flexShrink: 0,
        borderRadius: 0,
        border: "none",
        borderRight: "1px solid var(--color-border-tertiary) !important"
      }}>
        {/* New Chat Button */}
        <div style={{ padding: "16px", borderBottom: "1px solid var(--color-border-tertiary)" }}>
          <button
            onClick={handleNewChat}
            style={{
              width: "100%",
              height: 40,
              background: "linear-gradient(135deg, #e52d27, #b31217)",
              color: "#ffffff",
              border: "none",
              borderRadius: 8,
              fontSize: 13,
              fontWeight: 700,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 8,
              boxShadow: "0 4px 10px rgba(229,45,39,0.15)",
              transition: "transform 0.1s"
            }}
            onMouseOver={e => e.currentTarget.style.transform = "scale(1.02)"}
            onMouseOut={e => e.currentTarget.style.transform = "scale(1)"}
          >
            <svg style={{ width: 16, height: 16 }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
            Cuộc trò chuyện mới
          </button>
        </div>

        {/* Sessions Scroll List */}
        <div style={{ flex: 1, overflowY: "auto", padding: "12px 8px" }}>
          <span style={{ fontSize: 10, fontWeight: 800, color: "var(--color-text-secondary)", padding: "0 8px", display: "block", marginBottom: 8, letterSpacing: "0.5px" }}>LỊCH SỬ HỘI THOẠI</span>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {sessions.map((s) => {
              const isActive = currentSessionId === s.id;
              return (
                <div
                  key={s.id}
                  onClick={() => handleSelectSession(s.id)}
                  style={{
                    padding: "10px 12px",
                    borderRadius: 8,
                    background: isActive ? "var(--color-background-tertiary)" : "transparent",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    transition: "all 0.2s",
                    border: isActive ? "1.5px solid var(--color-border-info)" : "1.5px solid transparent"
                  }}
                  onMouseOver={e => {
                    if (!isActive) e.currentTarget.style.background = "var(--color-background-tertiary)";
                  }}
                  onMouseOut={e => {
                    if (!isActive) e.currentTarget.style.background = "transparent";
                  }}
                >
                  <div style={{ display: "flex", flexDirection: "column", overflow: "hidden", flex: 1, marginRight: 8 }}>
                    <span style={{ fontSize: 13, fontWeight: isActive ? 700 : 500, color: "var(--color-text-primary)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                      {s.title}
                    </span>
                    <span style={{ fontSize: 9, color: "var(--color-text-secondary)", marginTop: 2 }}>
                      {s.updated_at.split(".")[0].replace("T", " ")}
                    </span>
                  </div>
                  {/* Delete Button */}
                  <button
                    onClick={(e) => handleDeleteSession(e, s.id)}
                    style={{
                      background: "transparent",
                      border: "none",
                      cursor: "pointer",
                      padding: 4,
                      borderRadius: 4,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      color: "var(--color-text-secondary)"
                    }}
                    onMouseOver={e => e.currentTarget.style.color = "#ef4444"}
                    onMouseOut={e => e.currentTarget.style.color = "var(--color-text-secondary)"}
                  >
                    <svg style={{ width: 14, height: 14 }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="3 6 5 6 21 6" />
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                      <line x1="10" y1="11" x2="10" y2="17" />
                      <line x1="14" y1="11" x2="14" y2="17" />
                    </svg>
                  </button>
                </div>
              );
            })}
            {sessions.length === 0 && (
              <span style={{ fontSize: 12, fontStyle: "italic", color: "var(--color-text-secondary)", padding: "0 8px", marginTop: 10 }}>Chưa có cuộc trò chuyện nào.</span>
            )}
          </div>
        </div>
      </div>

      {/* CHAT MAIN INTERFACE: Message log & Inputs */}
      <div style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        height: "100%",
        overflow: "hidden"
      }}>
        {/* Top Header */}
        <div style={{
          padding: "16px 24px",
          background: "rgba(255, 255, 255, 0.45)",
          backdropFilter: "blur(12px)",
          borderBottom: "1px solid var(--color-border-tertiary)",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexShrink: 0
        }}>
          <div>
            <h1 style={{ fontSize: 18, fontWeight: 800, color: "var(--color-text-primary)", margin: 0, display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ display: "inline-flex", alignItems: "center" }}>
                <svg style={{ width: 20, height: 20, color: "#e52d27" }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/>
                  <path d="m5 3 1 2.5L8.5 6 6 7 5 9.5 4 7 1.5 6 4 5 5 3Z"/>
                  <path d="m19 17 1 2.5 2.5.5-2.5 1-1 2.5-1-2.5-2.5-1 2.5-1 1-2.5Z"/>
                </svg>
              </span>
              AI Revenue Copilot
            </h1>
            <p style={{ fontSize: 12, color: "var(--color-text-secondary)", margin: "4px 0 0 0" }}>
              Trợ lý đàm thoại thông minh hỗ trợ phân tích định giá thời gian thực
            </p>
          </div>

          {/* Status Indicator */}
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              background: statusData.vllm_connected ? "rgba(16, 185, 129, 0.1)" : "rgba(239, 68, 68, 0.1)",
              border: `1px solid ${statusData.vllm_connected ? "rgba(16, 185, 129, 0.2)" : "rgba(239, 68, 68, 0.2)"}`,
              padding: "6px 12px",
              borderRadius: 20,
              fontSize: 12,
              fontWeight: 700,
              color: statusData.vllm_connected ? "var(--color-text-success)" : "var(--color-text-danger)"
            }}>
              <span style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                backgroundColor: statusData.vllm_connected ? "#10b981" : "#ef4444",
                display: "inline-block",
                boxShadow: statusData.vllm_connected ? "0 0 8px #10b981" : "none"
              }} />
              <span>vLLM: {statusData.vllm_connected ? "Connected" : "Offline"}</span>
            </div>

            <div style={{
              fontSize: 11,
              color: "var(--color-text-secondary)",
              background: "var(--color-background-tertiary)",
              padding: "6px 12px",
              borderRadius: 20,
              border: "1px solid var(--color-border-tertiary)",
              fontWeight: 600
            }}>
              Model: <span style={{ fontFamily: "monospace", color: "var(--color-text-primary)" }}>{statusData.vllm_model.split("/").pop()}</span>
            </div>
          </div>
        </div>

        {/* Main Message History Area */}
        <div style={{
          flex: 1,
          overflowY: "auto",
          padding: "24px",
          display: "flex",
          flexDirection: "column",
          gap: 20
        }}>
          {messages.map((m, idx) => (
            <div key={idx} style={{
              display: "flex",
              flexDirection: "column",
              alignItems: m.role === "user" ? "flex-end" : "flex-start",
              maxWidth: "85%",
              alignSelf: m.role === "user" ? "flex-end" : "flex-start"
            }}>
              {/* Sender Label */}
              <span style={{
                fontSize: 11,
                fontWeight: 700,
                color: "var(--color-text-secondary)",
                marginBottom: 4,
                padding: "0 4px"
              }}>
                {m.role === "user" ? "MEMBER / REVENUE OPERATOR" : "VJ REVENUE COPILOT"}
              </span>

              {/* Message Card */}
              <div 
                className={m.role === "user" ? "" : "glass-panel"}
                style={{
                  background: m.role === "user" ? "linear-gradient(135deg, #e52d27, #b31217)" : "var(--color-background-primary)",
                  color: m.role === "user" ? "#ffffff" : "var(--color-text-primary)",
                  padding: "16px 20px",
                  borderRadius: 16,
                  boxShadow: m.role === "user" ? "0 4px 12px rgba(229,45,39,0.15)" : "0 4px 12px rgba(0,0,0,0.02)",
                  border: m.role === "user" ? "none" : "1px solid rgba(255,255,255,0.6)",
                  lineHeight: "1.6",
                  fontSize: 14,
                  wordBreak: "break-word"
                }}
              >
                {/* Thinking Details (CoT) */}
                {m.thinking && (
                  <details style={{
                    marginBottom: 14,
                    padding: "10px 14px",
                    background: m.role === "user" ? "rgba(255,255,255,0.15)" : "var(--color-background-tertiary)",
                    borderRadius: 10,
                    fontSize: 12,
                    border: m.role === "user" ? "none" : "1px solid var(--color-border-tertiary)",
                    color: m.role === "user" ? "rgba(255,255,255,0.9)" : "var(--color-text-secondary)"
                  }}>
                    <summary style={{
                      fontWeight: 800,
                      cursor: "pointer",
                      outline: "none",
                      userSelect: "none",
                      display: "flex",
                      alignItems: "center",
                      gap: 6
                    }}>
                      <svg style={{ width: 14, height: 14, color: "var(--color-text-secondary)" }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A5 5 0 0 0 8 8c0 1 .3 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5"/>
                        <path d="M9 18h6"/>
                        <path d="M10 22h4"/>
                      </svg>
                      Chuỗi suy luận logic (Chain of Thought)
                    </summary>
                    <div style={{
                      marginTop: 8,
                      whiteSpace: "pre-wrap",
                      fontFamily: "var(--font-sans)",
                      opacity: 0.95,
                      maxHeight: 200,
                      overflowY: "auto",
                      paddingRight: 6
                    }}>
                      {m.thinking}
                    </div>
                  </details>
                )}

                {/* Markdown text parser */}
                <div style={{ whiteSpace: "pre-wrap" }}>
                  {m.text.split("\n").map((line, lIdx) => {
                    let renderedLine = line;
                    const isBullet = line.startsWith("* ") || line.startsWith("- ");
                    const isNumbered = /^\d+\.\s/.test(line);
                    
                    const parts = renderedLine.split("**");
                    const contentElements = parts.map((part, pIdx) => {
                      if (pIdx % 2 === 1) {
                        return <strong key={pIdx} style={{ fontWeight: 800, color: m.role === "user" ? "#ffffff" : "#e52d27" }}>{part}</strong>;
                      }
                      return part;
                    });

                    if (isBullet) {
                      return <div key={lIdx} style={{ marginLeft: 16, marginBottom: 4, display: "list-item", listStyleType: "disc" }}>{contentElements}</div>;
                    }
                    if (isNumbered) {
                      return <div key={lIdx} style={{ marginLeft: 16, marginBottom: 4, display: "list-item", listStyleType: "decimal" }}>{contentElements}</div>;
                    }
                    return <div key={lIdx} style={{ marginBottom: 6 }}>{contentElements}</div>;
                  })}
                </div>

                {/* Tools Info */}
                {m.tools && m.tools.length > 0 && (
                  <div style={{
                    marginTop: 16,
                    paddingTop: 14,
                    borderTop: `1px solid ${m.role === "user" ? "rgba(255,255,255,0.2)" : "var(--color-border-tertiary)"}`,
                    display: "flex",
                    flexDirection: "column",
                    gap: 8
                  }}>
                    <span style={{ fontSize: 11, fontWeight: 800, letterSpacing: "0.5px", color: m.role === "user" ? "#ffffff" : "var(--color-text-secondary)", display: "flex", alignItems: "center", gap: 6 }}>
                      <svg style={{ width: 12, height: 12, color: m.role === "user" ? "#ffffff" : "var(--color-text-secondary)" }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
                      </svg>
                      CÁC CÔNG CỤ ĐÃ SỬ DỤNG:
                    </span>
                    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                      {m.tools.map((tool, tIdx) => (
                        <div key={tIdx} style={{
                          fontSize: 12,
                          background: m.role === "user" ? "rgba(0,0,0,0.15)" : "var(--color-background-tertiary)",
                          padding: "8px 12px",
                          borderRadius: 8,
                          border: m.role === "user" ? "none" : "1.5px solid var(--color-border-tertiary)"
                        }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 700, color: m.role === "user" ? "#fff" : "#e52d27" }}>
                            <svg style={{ width: 12, height: 12, fill: "currentColor" }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                              <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
                            </svg>
                            {tool.name}
                          </div>
                          <div style={{ fontSize: 11, color: m.role === "user" ? "rgba(255,255,255,0.7)" : "var(--color-text-secondary)", marginTop: 2 }}>
                            {tool.result}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Apply Price Card */}
                {m.action && m.action.type === "apply_price" && m.action.recommended_price !== undefined && (
                  <div style={{
                    marginTop: 18,
                    padding: "16px",
                    background: m.role === "user" ? "rgba(255, 255, 255, 0.15)" : "var(--color-background-info)",
                    border: m.role === "user" ? "1px solid rgba(255,255,255,0.3)" : "1px solid var(--color-border-info)",
                    borderRadius: 12,
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    gap: 16
                  }}>
                    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                      <span style={{ fontSize: 10, fontWeight: 800, opacity: 0.8 }}>HÀNH ĐỘNG KHUYẾN NGHỊ</span>
                      <span style={{ fontSize: 14, fontWeight: 800 }}>Chuyến {m.action.flight_no}: {m.action.recommended_price.toLocaleString()} VND</span>
                      <span style={{ fontSize: 11, opacity: 0.9 }}>Load Factor dự kiến: {(m.action.recommended_lf * 100).toFixed(1)}%</span>
                    </div>

                    <button
                      onClick={() => handleApplyPrice(m.action, idx)}
                      disabled={m.action.applied}
                      style={{
                        background: m.action.applied ? "var(--color-background-success)" : "linear-gradient(135deg, #e52d27, #b31217)",
                        color: "#ffffff",
                        border: "none",
                        padding: "8px 16px",
                        borderRadius: 8,
                        fontSize: 12,
                        fontWeight: 700,
                        cursor: m.action.applied ? "default" : "pointer",
                        boxShadow: "0 4px 10px rgba(0,0,0,0.15)",
                        transition: "transform 0.2s, box-shadow 0.2s"
                      }}
                      onMouseOver={e => !m.action.applied && (e.currentTarget.style.transform = "scale(1.05)")}
                      onMouseOut={e => !m.action.applied && (e.currentTarget.style.transform = "scale(1)")}
                    >
                      {m.action.applied ? (
                        <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                          <svg style={{ width: 12, height: 12 }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                            <polyline points="20 6 9 17 4 12" />
                          </svg>
                          Đã áp dụng
                        </span>
                      ) : "Áp dụng giá vé"}
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}

          {loading && (
            <div style={{ display: "flex", flexDirection: "column", gap: 4, maxWidth: "60%" }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-secondary)", padding: "0 4px" }}>
                VJ REVENUE COPILOT ĐANG SUY NGHĨ...
              </span>
              <div style={{
                background: "var(--color-background-secondary)",
                padding: "16px 20px",
                borderRadius: 16,
                border: "1px solid var(--color-border-tertiary)",
                display: "flex",
                alignItems: "center",
                gap: 8,
                color: "var(--color-text-secondary)",
                fontSize: 13,
                fontStyle: "italic"
              }}>
                <span className="copilot-spinner" style={{
                  width: 14,
                  height: 14,
                  border: "2px solid var(--color-border-tertiary)",
                  borderTop: "2px solid #e52d27",
                  borderRadius: "50%",
                  display: "inline-block",
                  animation: "spin 1s linear infinite"
                }} />
                <span>Chờ vLLM phân chia Tensor & Nemotron suy luận...</span>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Suggestions */}
        {messages.length === 1 && !loading && (
          <div style={{
            padding: "0 24px 12px 24px",
            display: "flex",
            gap: 10,
            flexWrap: "wrap",
            flexShrink: 0
          }}>
            {suggestions.map((s, idx) => (
              <button
                key={idx}
                onClick={() => handleSend(s)}
                className="glass-button"
                style={{
                  borderRadius: 20,
                  padding: "8px 16px",
                  fontSize: 12,
                  cursor: "pointer",
                  fontWeight: 600,
                  transition: "all 0.2s",
                  display: "flex",
                  alignItems: "center",
                  gap: 6
                }}
              >
                <svg style={{ width: 12, height: 12, color: "var(--color-text-secondary)" }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A5 5 0 0 0 8 8c0 1 .3 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5"/>
                  <path d="M9 18h6"/>
                </svg>
                {s}
              </button>
            ))}
          </div>
        )}

        {/* Input Bar */}
        <div style={{
          padding: "16px 24px 24px 24px",
          background: "rgba(255, 255, 255, 0.45)",
          backdropFilter: "blur(12px)",
          borderTop: "1px solid var(--color-border-tertiary)",
          display: "flex",
          gap: 12,
          alignItems: "center",
          flexShrink: 0
        }}>
          <input
            type="text"
            value={inputValue}
            onChange={e => setInputValue(e.target.value)}
            onKeyDown={e => e.key === "Enter" && handleSend()}
            placeholder="Hỏi Copilot tối ưu chuyến bay hoặc chặng bay..."
            disabled={loading}
            className="glass-input"
            style={{
              flex: 1,
              height: 48,
              padding: "0 20px",
              borderRadius: 24,
              fontSize: 14,
              outline: "none",
            }}
            onFocus={e => {
              e.currentTarget.style.borderColor = "var(--color-text-info)";
              e.currentTarget.style.boxShadow = "0 0 0 3px rgba(222, 31, 38, 0.15)";
            }}
            onBlur={e => {
              e.currentTarget.style.borderColor = "rgba(0, 0, 0, 0.08)";
              e.currentTarget.style.boxShadow = "none";
            }}
          />
          <button
            onClick={() => handleSend()}
            disabled={loading || !inputValue.trim()}
            style={{
              height: 48,
              padding: "0 24px",
              borderRadius: 24,
              background: loading || !inputValue.trim() ? "rgba(0, 0, 0, 0.04)" : "linear-gradient(135deg, #e52d27, #b31217)",
              color: loading || !inputValue.trim() ? "var(--color-text-secondary)" : "#ffffff",
              border: "none",
              fontSize: 14,
              fontWeight: 700,
              cursor: loading || !inputValue.trim() ? "default" : "pointer",
              display: "flex",
              alignItems: "center",
              gap: 6,
              boxShadow: loading || !inputValue.trim() ? "none" : "0 4px 12px rgba(229,45,39,0.2)"
            }}
          >
            <span>Gửi yêu cầu</span>
            <svg style={{ width: 16, height: 16 }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M17.8 19.2 16 11l3.5-3.5C21 6 21.5 4 21 3.5c-.5-.5-2.5 0-4 1.5L13.5 8.5 5.3 6.7c-.9-.2-1.9.1-2.4.9l-1.1 1.9c-.4.7-.2 1.7.5 2.2l6 4-2.2 2.2H3l-2 2 .7.7L3 21l3-1 2-2v-3.1l2.2-2.2 4 6c.5.7 1.5.9 2.2.5l1.9-1.1c.8-.5 1.1-1.5.9-2.4z"/>
            </svg>
          </button>
        </div>
      </div>

      {/* Toast Notification */}
      {toast && (
        <div style={{
          position: "fixed",
          top: 24,
          right: 24,
          zIndex: 9999,
          background: toast.type === "success" ? "var(--color-background-success)" : "var(--color-background-danger)",
          color: toast.type === "success" ? "var(--color-text-success)" : "var(--color-text-danger)",
          border: `1px solid ${toast.type === "success" ? "var(--color-border-success)" : "var(--color-border-danger)"}`,
          borderRadius: 12,
          padding: "12px 20px",
          boxShadow: "0 10px 25px -5px rgba(0,0,0,0.1), 0 8px 10px -6px rgba(0,0,0,0.1)",
          display: "flex",
          alignItems: "center",
          gap: 10,
          fontSize: 13,
          fontWeight: 600,
          animation: "slideIn 0.3s ease-out"
        }}>
          <span>
            {toast.type === "success" ? (
              <svg style={{ width: 16, height: 16, display: "block" }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            ) : (
              <svg style={{ width: 16, height: 16, display: "block" }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            )}
          </span>
          <span>{toast.message}</span>
        </div>
      )}

      {/* Inline styles for spinner rotation and toast slideIn */}
      <style>{`
        @keyframes spin {
          0% { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
        }
        @keyframes slideIn {
          from { transform: translateY(-20px); opacity: 0; }
          to { transform: translateY(0); opacity: 1; }
        }
      `}</style>
    </div>
  );
}
