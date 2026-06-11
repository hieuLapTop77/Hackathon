import { useState } from "react";
import { Routes, Route, useNavigate } from "react-router-dom";
import { useApi } from "./hooks/useApi";
import { useIsMobile } from "./hooks/useIsMobile";
import { Sidebar } from "./components/Sidebar";
import { OverviewPage } from "./pages/OverviewPage";
import { OptimizerPage } from "./pages/OptimizerPage";
import { SimulatorPage } from "./pages/SimulatorPage";
import { RoutesPage } from "./pages/RoutesPage";
import { UploadPage } from "./pages/UploadPage";
import { DashboardPage } from "./pages/DashboardPage";
import { CopilotPage } from "./pages/CopilotPage";
import { IconBot, IconTrendUp, IconTrendDown } from "./components/icons";
import { VietjetLogo } from "./components/VietjetLogo";
import ErrorBoundary from "./components/ErrorBoundary";

export default function App() {
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const [selectedFlight, setFlight] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const { data: health }          = useApi("/health");
  const { data: modelsData }      = useApi("/models");

  function handleSelectFlight(f) {
    setFlight(f);
    navigate("/optimizer");
  }

  function handleApplySuccess() {
    setRefreshKey(k => k + 1);
  }

  const bestModel = modelsData?.models?.find(m => m.best);
  const mapeLabel = bestModel?.mape != null ? `MAPE ${bestModel.mape.toFixed(2)}%` : null;
  const r2Label   = bestModel?.r2 != null ? `R2 ${bestModel.r2.toFixed(4)}` : null;

  return (
    <ErrorBoundary>
      {/* Liquid fluid drifting background elements */}
      <div className="fluid-bg-container">
        <div className="fluid-blob fluid-blob-1" />
        <div className="fluid-blob fluid-blob-2" />
        <div className="fluid-blob fluid-blob-3" />
      </div>

      <div className="app-shell" style={{
        display: "flex",
        background: "transparent",
        fontFamily: "var(--font-sans)", overflow: "hidden",
        position: "relative",
      }}>
        <Sidebar />

        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", position: "relative" }}>
          {/* Floating Dynamic Island (Web Header Redesign) */}
          <div className="dynamic-island" style={{
            position: "absolute",
            top: isMobile ? 8 : 12,
            left: "50%",
            transform: "translateX(-50%)",
            height: isMobile ? 42 : 48,
            display: "flex", alignItems: "center",
            padding: isMobile ? "0 14px" : "0 24px",
            gap: isMobile ? 8 : 16, flexShrink: 0,
            maxWidth: "calc(100vw - 16px)",
            overflow: "hidden",
            zIndex: 100,
          }}>
            {/* Logo Area */}
            <div style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer" }} onClick={() => navigate("/")}>
              <VietjetLogo height={22} color="var(--color-text-info)" />
              <div style={{
                height: 16, width: "1px", background: "var(--color-border-tertiary)", margin: "0 4px"
              }} />
              <div style={{ display: "flex", flexDirection: "column" }}>
                <span style={{ fontSize: 11, fontWeight: 800, color: "var(--color-text-primary)", letterSpacing: "0.2px" }}>Revenue Intelligence</span>
                <span style={{ fontSize: 7, color: "var(--color-text-secondary)", fontWeight: 600, marginTop: -2 }}>OPTIMIZATION SYSTEM</span>
              </div>
            </div>

            {!isMobile && <div style={{ width: 1, height: 20, background: "var(--color-border-tertiary)" }} />}

            {/* Model Status Badges — ẩn trên mobile để không tràn ngang */}
            {!isMobile && bestModel && (
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                {/* Best Model Name */}
                <div style={{
                  display: "flex", alignItems: "center", gap: 5,
                  background: "var(--color-background-info)",
                  border: "1px solid var(--color-border-info)",
                  borderRadius: 20, padding: "3px 10px",
                  color: "var(--color-text-info)", fontSize: 10, fontWeight: 700
                }}>
                  <IconBot />
                  <span>AI Best: {bestModel.name}</span>
                </div>

                {/* MAPE Performance */}
                {mapeLabel && (
                  <div style={{
                    display: "flex", alignItems: "center", gap: 4,
                    background: "var(--color-background-success)",
                    border: "0.5px solid var(--color-border-success)",
                    borderRadius: 20, padding: "3px 10px",
                    color: "var(--color-text-success)", fontSize: 10, fontWeight: 600
                  }}>
                    <IconTrendDown />
                    <span>MAPE: {bestModel.mape.toFixed(1)}%</span>
                  </div>
                )}

                {/* R2 Indicator */}
                {r2Label && (
                  <div style={{
                    display: "flex", alignItems: "center", gap: 4,
                    background: "rgba(255,255,255,0.04)",
                    border: "0.5px solid var(--color-border-tertiary)",
                    borderRadius: 20, padding: "3px 10px",
                    color: "var(--color-text-primary)", fontSize: 10, fontWeight: 600
                  }}>
                    <IconTrendUp />
                    <span>R²: {bestModel.r2.toFixed(3)}</span>
                  </div>
                )}
              </div>
            )}

            {/* Server Connection Status */}
            <div style={{
              display: "flex", alignItems: "center", gap: 6,
              background: health?.status === "ok" ? "var(--color-background-success)" : "var(--color-background-danger)",
              border: "0.5px solid",
              borderColor: health?.status === "ok" ? "var(--color-border-success)" : "var(--color-border-danger)",
              borderRadius: 20, padding: "3px 10px",
              color: health?.status === "ok" ? "var(--color-text-success)" : "var(--color-text-danger)",
              fontSize: 10, fontWeight: 600
            }}>
              <span style={{
                width: 5, height: 5, borderRadius: "50%",
                background: health?.status === "ok" ? "var(--color-text-success)" : "var(--color-text-danger)",
                display: "inline-block"
              }} />
              <span>{health?.status === "ok" ? "Connected" : "Offline"}</span>
            </div>
          </div>

          {/* Page content — mobile: chừa chỗ cho island gọn hơn ở trên và bottom nav ở dưới */}
          <div style={{ flex: 1, overflow: "hidden", display: "flex", paddingTop: isMobile ? 58 : 76, paddingBottom: isMobile ? 58 : 0 }}>
            <Routes>
              <Route path="/" element={<DashboardPage />} />
              <Route path="/overview" element={<OverviewPage onSelectFlight={handleSelectFlight} key={refreshKey} />} />
              <Route path="/optimizer" element={<OptimizerPage selectedFlight={selectedFlight} onApplySuccess={handleApplySuccess} />} />
              <Route path="/simulator" element={<SimulatorPage />} />
              <Route path="/routes" element={<RoutesPage />} />
              <Route path="/upload" element={<UploadPage onGoToOverview={() => navigate("/overview")} />} />
              <Route path="/copilot" element={<CopilotPage />} />
              {/* 404 Route fallback */}
              <Route path="*" element={
                <div style={{
                  padding: "60px 20px", textAlign: "center", width: "100%",
                  background: "var(--color-background-secondary)",
                  display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center"
                }}>
                  <h2 style={{ color: "var(--color-text-primary)", fontSize: "28px", margin: "0 0 10px 0" }}>404 - Không tìm thấy trang</h2>
                  <p style={{ color: "var(--color-text-secondary)", fontSize: "16px", margin: "0 0 24px 0" }}>Đường dẫn bạn truy cập không tồn tại hoặc đã bị thay đổi.</p>
                  <button
                    onClick={() => navigate("/")}
                    style={{
                      background: "var(--color-text-info)", color: "#fff", border: "none",
                      padding: "10px 20px", borderRadius: "6px", fontWeight: "600", cursor: "pointer"
                    }}
                  >
                    Quay lại trang chủ
                  </button>
                </div>
              } />
            </Routes>
          </div>
        </div>
      </div>
    </ErrorBoundary>
  );
}
