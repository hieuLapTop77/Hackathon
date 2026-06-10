import { useState, useEffect } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer, PieChart, Pie, Cell, LineChart, Line, AreaChart, Area
} from "recharts";
import { fmt, fmtM, fmtPct } from "../utils/formatters";
import { Spinner, ErrorBox } from "../components/Spinner";
import { IconRefresh, IconMapPin, IconCalendar, IconTrash, IconSparkles, IconDollar, IconPlane, IconTrendUp, IconUsers } from "../components/icons";

import { API_BASE_URL as API } from "../config";

const DEFAULT_CAPACITY = 230;
const COLORS = ["#0088FE", "#00C49F", "#FFBB28", "#FF8042", "#8884d8", "#82ca9d"];
const LF_COLORS = {
  high: "#10b981", // green
  mid: "#3b82f6",  // blue
  low: "#f59e0b",  // orange
  critical: "#ef4444" // red
};

export function DashboardPage() {
  const today = new Date().toISOString().split("T")[0];
  const [flightDate, setFlightDate] = useState(today);
  const [dep, setDep] = useState("");
  const [arr, setArr] = useState("");
  const [dbRoutes, setDbRoutes] = useState([]);

  const [summary, setSummary] = useState(null);
  const [routes, setRoutes] = useState([]);
  const [models, setModels] = useState([]);
  const [flights, setFlights] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchData = async (dateVal = flightDate, depVal = dep, arrVal = arr) => {
    setLoading(true);
    setError(null);
    try {
      const q = [];
      if (dateVal) q.push(`flight_date=${encodeURIComponent(dateVal)}`);
      if (depVal) q.push(`dep=${encodeURIComponent(depVal)}`);
      if (arrVal) q.push(`arr=${encodeURIComponent(arrVal)}`);
      const qs = q.length > 0 ? `?${q.join("&")}` : "";
      const flightsQs = q.length > 0 ? `?page_size=100&${q.join("&")}` : "?page_size=100";

      // Fetch summary, routes, models, and top flights
      const [resSummary, resRoutes, resModels, resFlights] = await Promise.all([
        fetch(`${API}/summary${qs}`),
        fetch(`${API}/routes${qs}`),
        fetch(`${API}/models`),
        fetch(`${API}/flights${flightsQs}`)
      ]);

      if (!resSummary.ok || !resRoutes.ok || !resModels.ok || !resFlights.ok) {
        throw new Error("Không thể tải toàn bộ dữ liệu từ API.");
      }

      const summaryData = await resSummary.json();
      const routesData = await resRoutes.json();
      const modelsData = await resModels.json();
      const flightsData = await resFlights.json();

      setSummary(summaryData);
      setRoutes(routesData);
      setModels(modelsData.models || []);
      setFlights(flightsData.items || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    // Fetch unique routes for selectors
    fetch(`${API}/db/routes`)
      .then(res => res.json())
      .then(data => setDbRoutes(data))
      .catch(err => console.error("Error fetching db routes:", err));
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => {
      fetchData(flightDate, dep, arr);
    }, 300);

    return () => clearTimeout(timer);
  }, [flightDate, dep, arr]);

  const handleFilterChange = (key, val) => {
    if (key === "flight_date") {
      setFlightDate(val);
    } else if (key === "dep") {
      setDep(val);
    } else if (key === "arr") {
      setArr(val);
    }
  };

  const handleClearFilters = () => {
    setFlightDate(today);
    setDep("");
    setArr("");
  };

  if (loading) return <div style={{ display: "flex", flex: 1, alignItems: "center", justifyContent: "center", minHeight: "80vh" }}><Spinner /></div>;
  if (error) return <div style={{ padding: 20 }}><ErrorBox msg={error} onRetry={() => fetchData(flightDate, dep, arr)} /></div>;

  // Process flight statuses for Donut Chart
  const statusCounts = { Optimal: 0, Warning: 0, Critical: 0 };
  flights.forEach(f => {
    if (f.lf >= 0.75) statusCounts.Optimal++;
    else if (f.lf >= 0.55) statusCounts.Warning++;
    else statusCounts.Critical++;
  });

  const donutData = [
    { name: "Tốt (LF >= 75%)", value: statusCounts.Optimal, color: LF_COLORS.high },
    { name: "Cảnh báo (LF 55%-75%)", value: statusCounts.Warning, color: LF_COLORS.low },
    { name: "Yếu (LF < 55%)", value: statusCounts.Critical, color: LF_COLORS.critical }
  ].filter(d => d.value > 0);

  // Process routes data for Bar Chart (Base Revenue vs AI Optimal Revenue)
  // Revenue = Price * Capacity * LoadFactor
  const routeRevData = routes.slice(0, 8).map(r => {
    const baseRev = r.avg_price * DEFAULT_CAPACITY * r.avg_lf;
    const aiRev = r.optimal_lf != null
      ? r.optimal_price * DEFAULT_CAPACITY * r.optimal_lf
      : baseRev * (1 + (r.revenue_delta_pct || 0) / 100);
    return {
      route: r.route,
      "Doanh thu hiện tại": Math.round(baseRev),
      "Doanh thu tối ưu AI": Math.round(aiRev),
      "Tỉ lệ tăng trưởng (%)": r.revenue_delta_pct
    };
  });

  // Process models performance mapping
  const modelsChartData = models.map(m => ({
    name: m.name,
    "Sai số MAPE (%)": m.mape || 0,
    "Độ khớp R2 (%)": (m.r2 || 0) * 100
  })).sort((a, b) => a["Sai số MAPE (%)"] - b["Sai số MAPE (%)"]);

  const hasUplift = summary && summary.revenue_delta_pct > 0;

  return (
    <div style={{
      flex: 1,
      overflow: "auto",
      padding: "20px 24px",
      display: "flex",
      flexDirection: "column",
      gap: 20,
      background: "transparent",
      height: "100%",
    }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h2 style={{ fontSize: 22, fontWeight: 800, color: "var(--color-text-primary)", letterSpacing: "-0.5px" }}>Báo cáo phân tích doanh thu</h2>
          <p style={{ fontSize: 12, color: "var(--color-text-secondary)", marginTop: 2 }}>
            Hệ thống phân tích What-If và tối ưu hóa giá vé máy bay thông minh bằng AI
          </p>
        </div>
        <button 
          onClick={() => fetchData(flightDate, dep, arr)} 
          className="glass-button"
          style={{
            padding: "8px 16px", borderRadius: "var(--border-radius-md)",
            color: "var(--color-text-primary)", fontSize: 12, fontWeight: 600, cursor: "pointer",
            display: "flex", alignItems: "center", gap: 6, boxShadow: "0 4px 12px rgba(0,0,0,0.15)"
          }}
        >
          <IconRefresh /> Làm mới dữ liệu
        </button>
      </div>

      {/* Filter Bar */}
      <div 
        className="glass-panel"
        style={{
          borderRadius: "var(--border-radius-lg)",
          padding: "16px 20px",
          display: "flex",
          alignItems: "flex-end",
          gap: 12,
          flexWrap: "wrap",
          boxShadow: "0 10px 30px rgba(0,0,0,0.2)"
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 150 }}>
          <label style={{ fontSize: 10, color: "var(--color-text-secondary)", textTransform: "uppercase", fontWeight: 700, letterSpacing: "0.05em", display: "flex", alignItems: "center", gap: 4 }}>
            <IconCalendar /> Ngày chuyến bay
          </label>
          <input
            type="date"
            value={flightDate}
            onChange={e => handleFilterChange("flight_date", e.target.value)}
            className="glass-input"
            style={{
              padding: "8px 12px",
              fontSize: 12,
              fontWeight: 500,
              outline: "none",
              border: "none",
              color: "#fff"
            }}
          />
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 130 }}>
          <label style={{ fontSize: 10, color: "var(--color-text-secondary)", textTransform: "uppercase", fontWeight: 700, letterSpacing: "0.05em", display: "flex", alignItems: "center", gap: 4 }}>
            <IconMapPin /> Điểm đi (DEP)
          </label>
          <select
            value={dep}
            onChange={e => handleFilterChange("dep", e.target.value)}
            className="glass-input"
            style={{
              padding: "8px 12px",
              fontSize: 12,
              fontWeight: 500,
              outline: "none",
              border: "none",
              cursor: "pointer",
              color: "#fff"
            }}
          >
            <option value="" style={{ background: "#1e293b" }}>Tất cả sân bay</option>
            {[...new Set(dbRoutes.map(r => r.str_Dep || r.route?.split("-")[0]).filter(Boolean))].map(d => (
              <option key={d} value={d} style={{ background: "#1e293b" }}>{d}</option>
            ))}
          </select>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 130 }}>
          <label style={{ fontSize: 10, color: "var(--color-text-secondary)", textTransform: "uppercase", fontWeight: 700, letterSpacing: "0.05em", display: "flex", alignItems: "center", gap: 4 }}>
            <IconMapPin /> Điểm đến (ARR)
          </label>
          <select
            value={arr}
            onChange={e => handleFilterChange("arr", e.target.value)}
            className="glass-input"
            style={{
              padding: "8px 12px",
              fontSize: 12,
              fontWeight: 500,
              outline: "none",
              border: "none",
              cursor: "pointer",
              color: "#fff"
            }}
          >
            <option value="" style={{ background: "#1e293b" }}>Tất cả sân bay</option>
            {[...new Set(dbRoutes.map(r => r.str_Arr || r.route?.split("-")[1]).filter(Boolean))].map(a => (
              <option key={a} value={a} style={{ background: "#1e293b" }}>{a}</option>
            ))}
          </select>
        </div>

        <div style={{ flex: 1 }} />

        <button
          onClick={handleClearFilters}
          className="glass-button"
          style={{
            padding: "8px 16px",
            borderRadius: "var(--border-radius-md)",
            color: "var(--color-text-secondary)",
            fontSize: 12,
            fontWeight: 600,
            cursor: "pointer",
            height: 36,
            display: "flex",
            alignItems: "center",
            gap: 6
          }}
        >
          <IconTrash /> Xóa lọc
        </button>
      </div>

      {/* Metrics Grid */}
      {summary && (
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
          gap: 16
        }}>
          {/* Card 1: Revenue Uplift */}
          <div 
            className="glass-panel glass-panel-hover"
            style={{
              borderRadius: "var(--border-radius-lg)", padding: "18px 22px",
              position: "relative", overflow: "hidden",
              border: "1px solid rgba(52, 211, 153, 0.25)",
              boxShadow: "0 8px 30px rgba(16, 185, 129, 0.05)"
            }}
          >
            <div style={{ fontSize: 10, color: "var(--color-text-secondary)", textTransform: "uppercase", fontWeight: 700, letterSpacing: "0.05em" }}>Tăng trưởng doanh thu</div>
            <div style={{ fontSize: 32, fontWeight: 900, color: "var(--color-text-success)", fontFamily: "var(--font-mono)", marginTop: 8 }}>
              +{summary.revenue_delta_pct}%
            </div>
            <div style={{ fontSize: 11, color: "var(--color-text-secondary)", marginTop: 4 }}>Dự kiến khi tối ưu giá bằng AI</div>
            <div style={{
              position: "absolute", right: 8, bottom: 8, opacity: 0.12, color: "var(--color-text-success)", pointerEvents: "none"
            }}>
              <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>
            </div>
          </div>

          {/* Card 2: Current Revenue */}
          <div 
            className="glass-panel glass-panel-hover"
            style={{
              borderRadius: "var(--border-radius-lg)", padding: "18px 22px",
              position: "relative", overflow: "hidden",
              boxShadow: "0 8px 30px rgba(0,0,0,0.15)"
            }}
          >
            <div style={{ fontSize: 10, color: "var(--color-text-secondary)", textTransform: "uppercase", fontWeight: 700, letterSpacing: "0.05em" }}>Doanh thu hiện tại</div>
            <div style={{ fontSize: 22, fontWeight: 800, color: "var(--color-text-primary)", fontFamily: "var(--font-mono)", marginTop: 8 }}>
              {fmt(summary.base_revenue_vnd)}
            </div>
            <div style={{ fontSize: 11, color: "var(--color-text-secondary)", marginTop: 4 }}>Tổng doanh thu chưa tối ưu</div>
            <div style={{
              position: "absolute", right: 8, bottom: 8, opacity: 0.1, color: "var(--color-text-primary)", pointerEvents: "none"
            }}>
              <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
            </div>
          </div>

          {/* Card 3: AI Optimized Revenue */}
          <div 
            className="glass-panel glass-panel-hover"
            style={{
              borderRadius: "var(--border-radius-lg)", padding: "18px 22px",
              position: "relative", overflow: "hidden",
              border: "1px solid rgba(255, 79, 94, 0.25)",
              boxShadow: "0 8px 30px rgba(255, 79, 94, 0.05)"
            }}
          >
            <div style={{ fontSize: 10, color: "var(--color-text-secondary)", textTransform: "uppercase", fontWeight: 700, letterSpacing: "0.05em" }}>Doanh thu mục tiêu AI</div>
            <div style={{ fontSize: 22, fontWeight: 800, color: "var(--color-text-info)", fontFamily: "var(--font-mono)", marginTop: 8 }}>
              {fmt(summary.ai_revenue_vnd)}
            </div>
            <div style={{ fontSize: 11, color: "var(--color-text-secondary)", marginTop: 4 }}>Ước lượng sau tối ưu hóa</div>
            <div style={{
              position: "absolute", right: 8, bottom: 8, opacity: 0.12, color: "var(--color-text-info)", pointerEvents: "none"
            }}>
              <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 3v18h18"/><path d="M18.7 8l-5.1 5.2-2.8-2.7L7 14.3"/></svg>
            </div>
          </div>

          {/* Card 4: Actionable Flights */}
          <div 
            className="glass-panel glass-panel-hover"
            style={{
              borderRadius: "var(--border-radius-lg)", padding: "18px 22px",
              position: "relative", overflow: "hidden",
              border: "1px solid rgba(251, 191, 38, 0.25)",
              boxShadow: "0 8px 30px rgba(251, 191, 38, 0.05)"
            }}
          >
            <div style={{ fontSize: 10, color: "var(--color-text-secondary)", textTransform: "uppercase", fontWeight: 700, letterSpacing: "0.05em" }}>Cần tối ưu giá</div>
            <div style={{ fontSize: 22, fontWeight: 800, color: summary.flights_need_action > 0 ? "var(--color-text-warning)" : "var(--color-text-primary)", fontFamily: "var(--font-mono)", marginTop: 8 }}>
              {summary.flights_need_action} / {summary.flights_total}
            </div>
            <div style={{ fontSize: 11, color: "var(--color-text-secondary)", marginTop: 4 }}>Số chuyến bay có LF thấp</div>
            <div style={{
              position: "absolute", right: 8, bottom: 8, opacity: 0.12, color: "var(--color-text-warning)", pointerEvents: "none"
            }}>
              <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 16V8a2 2 0 0 0-2-2h-3L12 3H9v3H6L3 8v8a2 2 0 0 0 2 2h3l4 3h3l-2-3h3a2 2 0 0 0 2-2z"/></svg>
            </div>
          </div>
        </div>
      )}

      {/* Main Charts Grid */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        gap: 20,
        alignItems: "stretch"
      }}>
        {/* Left Chart: Route Revenue Comparison */}
        <div 
          className="glass-panel glass-panel-hover"
          style={{
            borderRadius: "var(--border-radius-lg)", padding: "20px 24px",
            display: "flex", flexDirection: "column"
          }}
        >
          <h3 style={{ fontSize: 15, fontWeight: 700, color: "var(--color-text-primary)", marginBottom: 4 }}>So sánh doanh thu các chặng bay</h3>
          <p style={{ fontSize: 11, color: "var(--color-text-secondary)", marginBottom: 16 }}>So sánh doanh thu hiện tại và tiềm năng tăng trưởng khi điều chỉnh giá bằng AI</p>
          <div style={{ flex: 1, minHeight: 280 }}>
            {routeRevData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={routeRevData} margin={{ left: 10, right: 10, top: 10, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                  <XAxis dataKey="route" tick={{ fontSize: 10, fill: "var(--color-text-secondary)" }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: "var(--color-text-secondary)" }} axisLine={false} tickLine={false} tickFormatter={v => (v / 1e6).toFixed(1) + "M"} />
                  <Tooltip formatter={value => [fmt(value) + " VND", ""]} contentStyle={{ background: "rgba(15, 23, 42, 0.95)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 12, fontSize: 11, color: "#fff" }} />
                  <Legend tick={{ fontSize: 10 }} wrapperStyle={{ fontSize: 11 }} />
                  <Bar dataKey="Doanh thu hiện tại" fill="#475569" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="Doanh thu tối ưu AI" fill="var(--color-text-info)" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div style={{ display: "flex", height: "100%", alignItems: "center", justifyContent: "center", color: "var(--color-text-secondary)", fontSize: 12 }}>Chưa có dữ liệu các chặng bay</div>
            )}
          </div>
        </div>

        {/* Right Chart: Flight LF distribution */}
        <div 
          className="glass-panel glass-panel-hover"
          style={{
            borderRadius: "var(--border-radius-lg)", padding: "20px 24px",
            display: "flex", flexDirection: "column"
          }}
        >
          <h3 style={{ fontSize: 15, fontWeight: 700, color: "var(--color-text-primary)", marginBottom: 4 }}>Phân bổ trạng thái chuyến bay</h3>
          <p style={{ fontSize: 11, color: "var(--color-text-secondary)", marginBottom: 16 }}>Phân nhóm các chuyến bay dựa theo tỷ lệ lấp đầy (Load Factor)</p>
          <div style={{ display: "flex", flex: 1, minHeight: 280, alignItems: "center", justifyContent: "space-between" }}>
            <div style={{ width: "60%", height: "100%" }}>
              {donutData.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={donutData}
                      cx="50%"
                      cy="50%"
                      innerRadius={65}
                      outerRadius={90}
                      paddingAngle={4}
                      dataKey="value"
                    >
                      {donutData.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={{ background: "rgba(15, 23, 42, 0.95)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 12, fontSize: 11, color: "#fff" }} />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <div style={{ display: "flex", height: "100%", alignItems: "center", justifyContent: "center", color: "var(--color-text-secondary)", fontSize: 12 }}>Chưa có dữ liệu chuyến bay</div>
              )}
            </div>
            
            {/* Custom Legend */}
            <div style={{ width: "40%", display: "flex", flexDirection: "column", gap: 12, paddingRight: 10 }}>
              {donutData.map((d, index) => (
                <div key={index} style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 700 }}>
                    <span style={{ width: 8, height: 8, borderRadius: "50%", background: d.color, display: "inline-block" }} />
                    {d.name.split(" ")[0]}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--color-text-secondary)", paddingLeft: 14 }}>
                    {d.value} chuyến bay ({((d.value / flights.length) * 100).toFixed(1)}%)
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Secondary Charts Grid */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "2fr 1fr",
        gap: 20,
        alignItems: "stretch"
      }}>
        {/* Model Performance Comparison */}
        <div 
          className="glass-panel glass-panel-hover"
          style={{
            borderRadius: "var(--border-radius-lg)", padding: "20px 24px",
            display: "flex", flexDirection: "column"
          }}
        >
          <h3 style={{ fontSize: 15, fontWeight: 700, color: "var(--color-text-primary)", marginBottom: 4 }}>So sánh hiệu năng các mô hình AI</h3>
          <p style={{ fontSize: 11, color: "var(--color-text-secondary)", marginBottom: 16 }}>Chỉ số sai số MAPE (%) của từng mô hình ML huấn luyện. Cột thấp hơn là tốt hơn.</p>
          <div style={{ flex: 1, minHeight: 240 }}>
            {modelsChartData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={modelsChartData} margin={{ left: 10, right: 10, top: 10, bottom: 5 }}>
                  <defs>
                    <linearGradient id="colorMape" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="var(--color-text-info)" stopOpacity={0.4}/>
                      <stop offset="95%" stopColor="var(--color-text-info)" stopOpacity={0}/>
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                  <XAxis dataKey="name" tick={{ fontSize: 10, fill: "var(--color-text-secondary)" }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: "var(--color-text-secondary)" }} axisLine={false} tickLine={false} tickFormatter={v => v + "%"} />
                  <Tooltip contentStyle={{ background: "rgba(15, 23, 42, 0.95)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 12, fontSize: 11, color: "#fff" }} />
                  <Legend tick={{ fontSize: 10 }} wrapperStyle={{ fontSize: 11 }} />
                  <Area type="monotone" dataKey="Sai số MAPE (%)" stroke="var(--color-text-info)" fillOpacity={1} fill="url(#colorMape)" strokeWidth={2.5} />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div style={{ display: "flex", height: "100%", alignItems: "center", justifyContent: "center", color: "var(--color-text-secondary)", fontSize: 12 }}>Chưa nạp được chỉ số mô hình</div>
            )}
          </div>
        </div>

        {/* Airport Route breakdown */}
        <div 
          className="glass-panel glass-panel-hover"
          style={{
            borderRadius: "var(--border-radius-lg)", padding: "20px 24px",
            display: "flex", flexDirection: "column"
          }}
        >
          <h3 style={{ fontSize: 15, fontWeight: 700, color: "var(--color-text-primary)", marginBottom: 4 }}>Chặng bay phổ biến</h3>
          <p style={{ fontSize: 11, color: "var(--color-text-secondary)", marginBottom: 12 }}>Tổng quan các chặng bay hoạt động nhiều nhất</p>
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 10, overflow: "auto" }}>
            {routes.slice(0, 5).map((r, idx) => (
              <div key={idx} 
                className="glass-panel"
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 4,
                  padding: "10px 14px",
                  borderRadius: "var(--border-radius-md)",
                  border: "1px solid rgba(255, 255, 255, 0.05)"
                }}
                onMouseEnter={e => e.currentTarget.style.borderColor = "var(--color-border-info)"}
                onMouseLeave={e => e.currentTarget.style.borderColor = "rgba(255, 255, 255, 0.05)"}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontSize: 12, fontWeight: 700 }}>{r.route}</span>
                  <span style={{ fontSize: 10, background: "var(--color-background-info)", color: "var(--color-text-info)", padding: "2px 8px", borderRadius: 10, fontWeight: 600 }}>{r.count} chuyến</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--color-text-secondary)", marginTop: 2 }}>
                  <span>Giá TB: {fmt(r.avg_price)}đ</span>
                  <span>LF TB: {Math.round(r.avg_lf * 100)}%</span>
                </div>
              </div>
            ))}
            {routes.length === 0 && (
              <div style={{ display: "flex", flex: 1, alignItems: "center", justifyContent: "center", color: "var(--color-text-secondary)", fontSize: 11 }}>Không có dữ liệu chặng bay</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
