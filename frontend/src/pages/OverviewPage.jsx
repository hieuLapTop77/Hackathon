import { useState, useEffect, useCallback, useRef } from "react";
import { useApi } from "../hooks/useApi";
import { fmt, fmtM, fmtPct } from "../utils/formatters";
import { Spinner, ErrorBox, LfBar } from "../components/Spinner";
import { StatusBadge } from "../components/StatusBadge";
import { Pagination } from "../components/Pagination";
import { FlightDetailModal } from "../components/FlightDetailModal";
import { IconSearch, IconRefresh, IconMapPin, IconCalendar, IconSort, IconDollar, IconUsers, IconArrowRight, IconChevronUp, IconChevronDown, IconBot, IconCpu, IconTicket, IconFileText } from "../components/icons";

import { API_BASE_URL as API } from "../config";

const FARE_FAMILY_COLORS = {
  "Eco": "#4CAF50", "Eco-Premium": "#2196F3",
  "SkyBoss": "#9C27B0", "Business": "#FF9800",
  "Deluxe": "#FF5722",
};

// ── AI Suggestion cell ─────────────────────────────────────────────────────────
const CLASS_COLORS = {
  "Eco": "#4CAF50",
  "Deluxe": "#FF5722",
  "SkyBoss": "#9C27B0",
  "GDS": "#2196F3"
};

function AiSuggestionCell({ flight, aiPredictions, aiLoading, selectedModel }) {
  if (aiLoading) {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--color-text-secondary)" }}>
        <span style={{ width: 14, height: 14, border: "2px solid var(--color-border-info)", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.8s linear infinite" }} />
        <span style={{ fontSize: 12 }}>Đang tính...</span>
      </div>
    );
  }

  // Get data: either from batch predict state (aiPredictions) or default fallback (flight.ai_suggestions)
  let suggestions = {};
  if (selectedModel) {
    const flightPred = aiPredictions[flight.id];
    if (flightPred) {
      Object.keys(flightPred).forEach(k => {
        suggestions[k] = flightPred[k]?.predicted_price_vnd;
      });
    }
  } else {
    suggestions = flight.ai_suggestions || {};
  }

  const classes = ["Eco", "Deluxe", "SkyBoss", "GDS"];
  
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 8px", maxWidth: 350 }}>
      {classes.map(cls => {
        const val = suggestions[cls];
        if (val == null) return null;
        
        return (
          <div key={cls} style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            background: "var(--color-background-primary)",
            padding: "4px 8px",
            borderRadius: 8,
            border: "0.5px solid var(--color-border-tertiary)",
            fontSize: 12,
            fontFamily: "var(--font-mono)",
            boxShadow: "0 1px 3px rgba(0,0,0,0.04)"
          }}>
            <span style={{
              width: 7,
              height: 7,
              borderRadius: "50%",
              background: CLASS_COLORS[cls] || "#666"
            }} />
            <span style={{ color: "var(--color-text-secondary)", fontWeight: 600, fontSize: 11 }}>{cls}:</span>
            <span style={{ fontWeight: 800, color: "var(--color-text-primary)", fontSize: 12 }}>{fmt(val)}</span>
          </div>
        );
      })}
      {Object.keys(suggestions).length === 0 && (
        <span style={{ color: "var(--color-text-secondary)", fontSize: 12 }}>--</span>
      )}
    </div>
  );
}

export function OverviewPage({ onSelectFlight }) {
  const today = new Date().toISOString().split("T")[0];

  const [filters, setFilters] = useState({
    dep: "", arr: "", flight_date: "", sort_by: "flight_date", sort_dir: "asc",
    fare_family: ""
  });
  const [selectedModel, setSelectedModel] = useState("");  // "" = no model selected (use default)
  const [flights, setFlights]       = useState(null);
  const [totalCount, setTotalCount] = useState(0);
  const [flLoading, setFlLoading]  = useState(false);
  const [flError, setFlError]     = useState(null);
  const [selectedFlight, setSelectedFlight] = useState(null);
  const [page, setPage]           = useState(1);
  const [pageSize, setPageSize]   = useState(15);

  // AI prediction state
  const [aiPredictions, setAiPredictions] = useState({}); // {flightId: {predicted_price_vnd, model_used}}
  const [aiLoading, setAiLoading] = useState(false);
  const aiAbortRef = useRef(null);

  const summaryQs = `?dep=${encodeURIComponent(filters.dep)}&arr=${encodeURIComponent(filters.arr)}&flight_date=${encodeURIComponent(filters.flight_date)}&fare_family=${encodeURIComponent(filters.fare_family)}`;
  const { data: summary, loading: sl, error: se, refetch: sr } = useApi(`/summary${summaryQs}`);
  const { data: dbRoutes } = useApi("/db/routes");
  const { data: modelsData } = useApi("/models");

  const setFilter = (key, val) => {
    setFilters(prev => ({ ...prev, [key]: val }));
    setPage(1);
  };

  const buildQs = () => {
    const p = new URLSearchParams();
    if (filters.dep)        p.set("dep", filters.dep);
    if (filters.arr)        p.set("arr", filters.arr);
    if (filters.flight_date) p.set("flight_date", filters.flight_date);
    if (filters.fare_family) p.set("fare_family", filters.fare_family);
    if (filters.sort_by)    p.set("sort_by", filters.sort_by);
    if (filters.sort_dir)   p.set("sort_dir", filters.sort_dir);
    p.set("page", page);
    p.set("page_size", pageSize);
    return p.toString();
  };

  const handleSearch = useCallback(async () => {
    setFlLoading(true);
    setFlError(null);
    setAiPredictions({});
    try {
      const res = await fetch(`${API}/flights?${buildQs()}`);
      if (!res.ok) throw new Error(`API error ${res.status}`);
      const data = await res.json();
      if (Array.isArray(data)) {
        setFlights(data);
        setTotalCount(data.length);
      } else if (data.items) {
        setFlights(data.items);
        setTotalCount(data.total ?? data.items.length);
      } else if (data.data) {
        setFlights(data.data);
        setTotalCount(data.total ?? data.data.length);
      } else {
        setFlights([]);
        setTotalCount(0);
      }
    } catch (e) {
      setFlError(e.message);
    } finally {
      setFlLoading(false);
    }
  }, [filters.dep, filters.arr, filters.flight_date, filters.fare_family, filters.sort_by, filters.sort_dir, page, pageSize]);

  useEffect(() => { handleSearch(); }, [handleSearch]);

  // ── Gọi batch predict khi có flights + selectedModel ──────────────────────
  const runBatchPredict = useCallback(async (flightList, modelName) => {
    if (!flightList || flightList.length === 0) return;
    if (!modelName) { setAiPredictions({}); return; }

    // Cancel any in-flight request
    if (aiAbortRef.current) aiAbortRef.current.abort();
    aiAbortRef.current = new AbortController();

    setAiLoading(true);
    setAiPredictions({});

    try {
      const payload = {
        model_name: modelName,
        flights: flightList.map(f => {
          const [dep, arr] = (f.route || "").split("->").map(s => s.trim());
          return {
            id: f.id,
            lead_time_days: (f.lead_time_days != null && f.lead_time_days >= 0) ? f.lead_time_days : 30,
            LF_by_date: (f.lf != null && f.lf >= 0 && f.lf <= 1) ? f.lf : 0.65,
            LF_by_fare: (f.LF_by_fare != null && f.LF_by_fare >= 0) ? f.LF_by_fare : (f.lf ?? 0.40),
            booking_velocity_3d: f.booking_velocity_3d ?? 0.02,
            booking_velocity_7d: f.booking_velocity_7d ?? 0.05,
            Weekday: f.Weekday ?? (new Date(f.flight_date || today).getDay() || 4),
            IsHoliday: f.IsHoliday ?? 0,
            is_oneway: f.is_oneway ?? 1,
            lng_fuel: (f.lng_fuel != null && f.lng_fuel > 0) ? f.lng_fuel : 93.86,
            capacity: (f.capacity != null && f.capacity > 0) ? f.capacity : 230,
            count_sked: f.count_sked ?? 3,
            fare_family: (f.fare_family && f.fare_family.trim()) ? f.fare_family.trim() : "Eco",
            fare_category: (f.fare_category && f.fare_category.trim()) ? f.fare_category.trim() : "B",
            dep: dep || "SGN",
            arr: arr || "HAN",
            current_price: (f.price != null && f.price > 0) ? f.price : null,
          };
        }),
      };

      const res = await fetch(`${API}/predict-for-flights`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: aiAbortRef.current.signal,
      });
      if (!res.ok) throw new Error(`Predict error ${res.status}`);
      const data = await res.json();
      setAiPredictions(data.predictions || {});
    } catch (e) {
      if (e.name !== "AbortError") console.error("Batch predict failed:", e);
    } finally {
      setAiLoading(false);
    }
  }, [today]);

  // Re-run prediction khi flights hoặc selectedModel thay đổi
  useEffect(() => {
    if (flights && flights.length > 0 && selectedModel) {
      runBatchPredict(flights, selectedModel);
    } else {
      setAiPredictions({});
    }
  }, [flights, selectedModel, runBatchPredict]);

  const toggleSort = (colKey) => {
    if (filters.sort_by === colKey) {
      const nextDir = filters.sort_dir === "asc" ? "desc" : "asc";
      setFilter("sort_dir", nextDir);
    } else {
      setFilter("sort_by", colKey);
      setFilter("sort_dir", "asc");
    }
  };

  const renderSortHeader = (label, colKey) => {
    const isSorted = filters.sort_by === colKey;
    const dir = filters.sort_dir;
    return (
      <th
        onClick={() => toggleSort(colKey)}
        style={{
          padding: "10px 12px",
          color: isSorted ? "var(--color-text-info)" : "var(--color-text-secondary)",
          fontWeight: isSorted ? 700 : 600,
          textAlign: "left", fontSize: 10, textTransform: "uppercase", letterSpacing: ".04em",
          whiteSpace: "nowrap", cursor: "pointer", userSelect: "none",
          transition: "all 0.15s"
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span>{label}</span>
          <span style={{ display: "inline-flex", opacity: isSorted ? 1 : 0.4 }}>
            {isSorted ? (
              dir === "asc" ? <IconChevronUp /> : <IconChevronDown />
            ) : (
              <IconSort />
            )}
          </span>
        </div>
      </th>
    );
  };

  const handleFlightClick = (f) => {
    setSelectedFlight(f);
    onSelectFlight && onSelectFlight(f);
  };

  const handleModalClose = () => { setSelectedFlight(null); handleSearch(); };

  const handleReset = () => {
    setFilters({ dep: "", arr: "", flight_date: "", sort_by: "flight_date", sort_dir: "asc", fare_family: "" });
    setSelectedModel("");
    setPage(1);
    setPageSize(15);
  };

  const handlePageSizeChange = (newSize) => {
    setPageSize(newSize);
    setPage(1);
  };

  const deps = [...new Set((dbRoutes || []).map(r => r.str_Dep || r.route?.split("-")[0]).filter(Boolean))];
  const arrs = [...new Set((dbRoutes || []).map(r => r.str_Arr || r.route?.split("-")[1]).filter(Boolean))];
  const totalFlights = totalCount;
  const modelList = modelsData?.models || [];

  if (sl && !summary) return <Spinner />;

  return (
    <>
      <div style={{ flex: 1, overflow: "auto", padding: "20px 24px", display: "flex", flexDirection: "column", gap: 16, height: "100%", minHeight: 0, background: "transparent" }}>

        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 18, fontWeight: 800, color: "var(--color-text-primary)", letterSpacing: "-0.5px" }}>Danh sách chuyến bay</span>
            <span 
              className="glass-panel"
              style={{ 
                background: "rgba(16, 185, 129, 0.15)", 
                color: "var(--color-text-success)", 
                padding: "3px 10px", 
                borderRadius: 20, 
                fontSize: 10, 
                fontWeight: 700, 
                display: "flex", 
                alignItems: "center", 
                gap: 5,
                border: "1px solid rgba(16, 185, 129, 0.25)"
              }}
            >
              <span style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--color-text-success)", display: "inline-block" }} />
              Live data
            </span>
          </div>
          <span style={{ fontSize: 11, color: "var(--color-text-secondary)", fontWeight: 600 }}>{filters.flight_date || today}</span>
        </div>

        {se && <ErrorBox msg={se} onRetry={sr} />}
        {flError && <ErrorBox msg={flError} onRetry={handleSearch} />}

        {/* Filter bar */}
        <div 
          className="glass-panel"
          style={{ 
            borderRadius: "var(--border-radius-lg)", 
            padding: "16px 20px", 
            display: "flex", 
            gap: 12, 
            alignItems: "flex-end", 
            flexWrap: "wrap",
            boxShadow: "0 10px 30px rgba(0,0,0,0.2)"
          }}
        >
          
          <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 120 }}>
            <label style={{ fontSize: 10, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: ".05em", display: "flex", alignItems: "center", gap: 4, fontWeight: 700 }}>
              <IconMapPin /> Điểm đi
            </label>
            <select 
              value={filters.dep} 
              onChange={e => setFilter("dep", e.target.value)}
              className="glass-input"
              style={{ padding: "8px 12px", fontSize: 12, cursor: "pointer", outline: "none", border: "none", color: "#fff" }}
            >
              <option value="" style={{ background: "#1e293b" }}>Tất cả</option>
              {deps.map(d => <option key={d} value={d} style={{ background: "#1e293b" }}>{d}</option>)}
            </select>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 120 }}>
            <label style={{ fontSize: 10, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: ".05em", display: "flex", alignItems: "center", gap: 4, fontWeight: 700 }}>
              <IconMapPin /> Điểm đến
            </label>
            <select 
              value={filters.arr} 
              onChange={e => setFilter("arr", e.target.value)}
              className="glass-input"
              style={{ padding: "8px 12px", fontSize: 12, cursor: "pointer", outline: "none", border: "none", color: "#fff" }}
            >
              <option value="" style={{ background: "#1e293b" }}>Tất cả</option>
              {arrs.map(a => <option key={a} value={a} style={{ background: "#1e293b" }}>{a}</option>)}
            </select>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 130 }}>
            <label style={{ fontSize: 10, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: ".05em", display: "flex", alignItems: "center", gap: 4, fontWeight: 700 }}>
              <IconCalendar /> Ngày bay
            </label>
            <input 
              type="date" 
              value={filters.flight_date} 
              onChange={e => setFilter("flight_date", e.target.value)}
              className="glass-input"
              style={{ padding: "8px 12px", fontSize: 12, outline: "none", border: "none", color: "#fff" }} 
            />
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 110 }}>
            <label style={{ fontSize: 10, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: ".05em", display: "flex", alignItems: "center", gap: 4, fontWeight: 700 }}>
              <IconTicket /> Hạng vé
            </label>
            <select 
              value={filters.fare_family} 
              onChange={e => setFilter("fare_family", e.target.value)}
              className="glass-input"
              style={{ padding: "8px 12px", fontSize: 12, cursor: "pointer", outline: "none", border: "none", color: "#fff" }}
            >
              <option value="" style={{ background: "#1e293b" }}>Tất cả</option>
              <option value="Eco" style={{ background: "#1e293b" }}>Eco</option>
              <option value="Deluxe" style={{ background: "#1e293b" }}>Deluxe</option>
              <option value="SkyBoss" style={{ background: "#1e293b" }}>SkyBoss</option>
              <option value="Business" style={{ background: "#1e293b" }}>GDS</option>
            </select>
          </div>

          {/* ── Model selector ─────────────────────────────────────── */}
          <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 180 }}>
            <label style={{ fontSize: 10, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: ".05em", display: "flex", alignItems: "center", gap: 4, fontWeight: 700 }}>
              <IconCpu /> AI Model gợi ý
            </label>
            <div style={{ position: "relative" }}>
              <select
                value={selectedModel}
                onChange={e => setSelectedModel(e.target.value)}
                className="glass-input"
                style={{
                  padding: "8px 32px 8px 12px", 
                  fontSize: 12, width: "100%", appearance: "none", cursor: "pointer",
                  fontWeight: selectedModel ? 600 : 400, outline: "none",
                  border: selectedModel ? "1px solid var(--color-border-info)" : "none",
                  color: selectedModel ? "var(--color-text-info)" : "#fff"
                }}
              >
                <option value="" style={{ background: "#1e293b", color: "#fff" }}>-- Mặc định --</option>
                {modelList.map(m => (
                  <option key={m.name} value={m.name} style={{ background: "#1e293b", color: "#fff" }}>
                    {m.name}{m.best ? " (Best)" : ""}{m.mape != null ? ` (${m.mape.toFixed(0)}%)` : ""}
                  </option>
                ))}
              </select>
              <span style={{ position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)", pointerEvents: "none", fontSize: 9, color: "var(--color-text-secondary)" }}>▼</span>
            </div>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 105 }}>
            <label style={{ fontSize: 10, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: ".05em", display: "flex", alignItems: "center", gap: 4, fontWeight: 700 }}>
              <IconFileText /> Số dòng
            </label>
            <select 
              value={pageSize} 
              onChange={e => handlePageSizeChange(parseInt(e.target.value))}
              className="glass-input"
              style={{ padding: "8px 12px", fontSize: 12, cursor: "pointer", outline: "none", border: "none", color: "#fff" }}
            >
              <option value="15" style={{ background: "#1e293b" }}>15 dòng</option>
              <option value="30" style={{ background: "#1e293b" }}>30 dòng</option>
              <option value="50" style={{ background: "#1e293b" }}>50 dòng</option>
              <option value="100" style={{ background: "#1e293b" }}>100 dòng</option>
            </select>
          </div>

          <div style={{ flex: 1 }} />
          <button 
            onClick={() => { setPage(1); handleSearch(); }} 
            disabled={flLoading}
            className="glass-button"
            style={{ 
              padding: "8px 16px", borderRadius: "var(--border-radius-md)", border: "none",
              color: flLoading ? "var(--color-text-secondary)" : "var(--color-text-info)",
              fontSize: 12, fontWeight: 700, cursor: flLoading ? "not-allowed" : "pointer",
              opacity: flLoading ? 0.6 : 1, display: "flex", alignItems: "center", gap: 6, height: 36,
              boxShadow: "0 4px 12px rgba(255, 79, 94, 0.1)"
            }}
          >
            <IconSearch /> {flLoading ? "Searching..." : "Search"}
          </button>
          <button 
            onClick={handleReset}
            className="glass-button"
            style={{ 
              padding: "8px 16px", borderRadius: "var(--border-radius-md)",
              color: "var(--color-text-secondary)", fontSize: 12, fontWeight: 600, cursor: "pointer",
              display: "flex", alignItems: "center", gap: 6, height: 36 
            }}
          >
            <IconRefresh /> Reset
          </button>
        </div>

        {/* Summary stats */}
        {summary && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 12, opacity: sl ? 0.6 : 1, transition: "opacity 0.15s ease-in-out" }}>
            {[
              { label: "Load factor trung bình", value: `${Math.round(summary.avg_load_factor * 100)}%`, sub: "Tỷ lệ lấp đầy bình quân" },
              { label: "Cần tối ưu giá", value: `${summary.flights_need_action} / ${summary.flights_total}`, sub: "chuyến bay cần điều chỉnh", color: "var(--color-text-warning)", warningBorder: true },
            ].map(({ label, value, sub, color, warningBorder }) => (
              <div 
                key={label} 
                className="glass-panel glass-panel-hover"
                style={{ 
                  borderRadius: "var(--border-radius-md)", 
                  padding: "14px 18px",
                  border: warningBorder ? "1px solid rgba(251, 191, 38, 0.25)" : "1px solid rgba(255, 255, 255, 0.08)"
                }}
              >
                <div style={{ fontSize: 10, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: ".05em", marginBottom: 6, display: "flex", alignItems: "center", gap: 4, fontWeight: 700 }}>
                  {label === "Load factor trung bình" && <IconUsers />}
                  {label}
                </div>
                <div style={{ fontSize: 22, fontWeight: 800, fontFamily: "var(--font-mono)", color: color || undefined }}>
                  <span key={value} className="number-change-pulse">{value}</span>
                </div>
                <div style={{ fontSize: 10, color: color || "var(--color-text-secondary)", marginTop: 4 }}>{sub}</div>
              </div>
            ))}
          </div>
        )}

        {/* Flights table */}
        <div 
          className="glass-panel"
          style={{ 
            borderRadius: "var(--border-radius-lg)", 
            overflow: "hidden", 
            display: "flex", 
            flexDirection: "column", 
            flex: 1, 
            minHeight: 0,
            boxShadow: "0 10px 40px rgba(0,0,0,0.3)"
          }}
        >
          <div style={{ padding: "12px 16px", borderBottom: "1px solid rgba(255,255,255,0.08)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontSize: 12, fontWeight: 700, color: "var(--color-text-primary)" }}>Danh sách chuyến bay</span>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              {selectedModel && (
                <span 
                  className="glass-panel"
                  style={{ 
                    fontSize: 10, padding: "3px 10px", borderRadius: 20, 
                    background: "var(--color-background-info)", 
                    color: "var(--color-text-info)", 
                    fontWeight: 700, 
                    display: "flex", 
                    alignItems: "center", 
                    gap: 5,
                    border: "1px solid var(--color-border-info)"
                  }}
                >
                  <IconBot />
                  <span>{selectedModel}{aiLoading ? " • Đang dự đoán..." : ""}</span>
                </span>
              )}
              <span style={{ fontSize: 11, color: "var(--color-text-secondary)", fontWeight: 600 }}>
                {flLoading ? "Loading..." : totalFlights ? `${totalFlights} flights` : "--"}
              </span>
            </div>
          </div>

          {flLoading && <div style={{ padding: 32, textAlign: "center" }}><Spinner /></div>}
          {!flLoading && (!flights || flights.length === 0) && (
            <div style={{ padding: "24px 16px", textAlign: "center", color: "var(--color-text-secondary)", fontSize: 12 }}>
              No flights found. Please change filters or upload data.
            </div>
          )}
          {!flLoading && flights && flights.length > 0 && (
            <>
              <div style={{ flex: 1, overflowY: "auto", overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                  <thead>
                    <tr style={{ borderBottom: "1px solid rgba(255, 255, 255, 0.08)", background: "rgba(255, 255, 255, 0.02)" }}>
                      {renderSortHeader("Ngày bay", "flight_date")}
                      {renderSortHeader("Tuyến", "route")}
                      <th style={{ padding: "10px 12px", color: "var(--color-text-secondary)", fontWeight: 600, textAlign: "left", fontSize: 10, textTransform: "uppercase", letterSpacing: ".04em" }}>
                        Hạng vé
                      </th>
                      {renderSortHeader("LF", "lf")}
                      {renderSortHeader("Giá hiện tại", "price")}
                      <th style={{
                        padding: "10px 12px",
                        color: selectedModel ? "var(--color-text-info)" : "var(--color-text-secondary)",
                        fontWeight: selectedModel ? 700 : 600,
                        textAlign: "left", fontSize: 10, textTransform: "uppercase", letterSpacing: ".04em", whiteSpace: "nowrap"
                      }}>
                        {selectedModel ? (
                          <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                            <IconBot />
                            <span>Gợi ý {selectedModel}</span>
                          </div>
                        ) : "AI Gợi ý"}
                      </th>
                      <th style={{ padding: "10px 12px", color: "var(--color-text-secondary)", fontWeight: 600, textAlign: "left", fontSize: 10, textTransform: "uppercase", letterSpacing: ".04em" }}>
                        Trạng thái
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {flights.map(f => {
                      const needsAction = f.lf < 0.55;
                      return (
                        <tr key={f.id}
                          onClick={() => handleFlightClick(f)}
                          style={{
                            borderBottom: "1px solid rgba(255,255,255,0.04)",
                            cursor: "pointer",
                            transition: "all .2s cubic-bezier(0.16, 1, 0.3, 1)",
                            borderLeft: needsAction ? "4px solid var(--color-text-warning)" : "4px solid transparent"
                          }}
                          onMouseEnter={e => e.currentTarget.style.background = "rgba(255, 255, 255, 0.04)"}
                          onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                          <td style={{ padding: "11px 12px", fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--color-text-secondary)" }}>{f.flight_date || "--"}</td>
                          <td style={{ padding: "11px 12px", fontSize: 12 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                              <span style={{ fontWeight: 600 }}>{f.route?.split("->")[0] || "--"}</span>
                              <IconArrowRight />
                              <span style={{ fontWeight: 600 }}>{f.route?.split("->")[1] || ""}</span>
                            </div>
                          </td>
                          <td style={{ padding: "11px 12px" }}>
                            <span style={{ padding: "2px 8px", borderRadius: 12, fontSize: 10, fontWeight: 700, background: FARE_FAMILY_COLORS[f.fare_family] || "#666", color: "#fff", display: "inline-block" }}>
                              {f.fare_family || f.fare_category || "--"}
                            </span>
                          </td>
                          <td style={{ padding: "11px 12px" }}><LfBar lf={f.lf} /></td>
                          <td style={{ padding: "11px 12px", fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--color-text-primary)", fontWeight: 600 }}>{fmt(f.price || 0)}</td>
                          <td style={{ padding: "11px 12px" }}>
                            <AiSuggestionCell
                              flight={f}
                              aiPredictions={aiPredictions}
                              aiLoading={!!(aiLoading && selectedModel)}
                              selectedModel={selectedModel}
                            />
                          </td>
                          <td style={{ padding: "11px 12px" }}><StatusBadge status={f.status} /></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <div style={{ padding: "12px 16px", borderTop: "1px solid rgba(255,255,255,0.08)", display: "flex", justifyContent: "flex-end", background: "rgba(0,0,0,0.05)" }}>
                <Pagination page={page} total={totalFlights} pageSize={pageSize} onChange={p => setPage(p)} />
              </div>
            </>
          )}
        </div>
      </div>

      {selectedFlight && (
        <FlightDetailModal flight={selectedFlight} onClose={handleModalClose} onSave={() => {}} />
      )}
    </>
  );
}
