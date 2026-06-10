import React from "react";

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error("ErrorBoundary caught an error:", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          padding: "40px 20px",
          textAlign: "center",
          fontFamily: "system-ui, -apple-system, sans-serif",
          maxWidth: "600px",
          margin: "80px auto",
          background: "#fff",
          borderRadius: "12px",
          boxShadow: "0 10px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1)",
          border: "1px solid #fee2e2"
        }}>
          <svg style={{ width: "64px", height: "64px", margin: "0 auto 20px auto", display: "block", color: "#ef4444" }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
            <line x1="12" y1="9" x2="12" y2="13" />
            <line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
          <h2 style={{ color: "#b91c1c", margin: "0 0 10px 0", fontSize: "24px" }}>Đã xảy ra lỗi hệ thống</h2>
          <p style={{ color: "#4b5563", fontSize: "16px", lineHeight: "1.5", margin: "0 0 24px 0" }}>
            Ứng dụng gặp sự cố không mong muốn trong quá trình kết xuất. Vui lòng tải lại trang hoặc liên hệ quản trị viên.
          </p>
          <div style={{
            background: "#f9fafb",
            padding: "16px",
            borderRadius: "8px",
            border: "1px solid #e5e7eb",
            textAlign: "left",
            fontSize: "13px",
            fontFamily: "monospace",
            color: "#ef4444",
            overflowX: "auto",
            marginBottom: "24px",
            whiteSpace: "pre-wrap"
          }}>
            {this.state.error && this.state.error.toString()}
          </div>
          <button
            onClick={() => window.location.reload()}
            style={{
              background: "#e52d27",
              color: "#fff",
              border: "none",
              padding: "12px 24px",
              fontSize: "15px",
              fontWeight: "600",
              borderRadius: "6px",
              cursor: "pointer",
              transition: "background 0.2s"
            }}
            onMouseEnter={(e) => e.target.style.background = "#b31b17"}
            onMouseLeave={(e) => e.target.style.background = "#e52d27"}
          >
            Tải lại trang
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
