import { useState, useEffect } from "react";
import { useApi } from "../hooks/useApi";
import { fmt, fmtPct, getLFColor } from "../utils/formatters";
import { Spinner, ErrorBox } from "../components/Spinner";
import { IconMapPin, IconCalendar, IconRefresh, IconChevronUp, IconChevronDown, IconUsers, IconPlane } from "../components/icons";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";

export function RoutesPage() {
  const today = new Date().toISOString().split("T")[0];
  const [filters, setFilters] = useState({
    dep: "", arr: "", flight_date: today,
  });
  const [appliedFilters, setAppliedFilters] = useState(filters);
  const [isTyping, setIsTyping] = useState(false);

  // Get airports list
  const { data: airports } = useApi("/airports");

  // Build query string from applied filters
  const queryParams = new URLSearchParams();
  if (appliedFilters.flight_date) queryParams.set("flight_date", appliedFilters.flight_date);
  if (appliedFilters.dep) queryParams.set("dep", appliedFilters.dep);
  if (appliedFilters.arr) queryParams.set("arr", appliedFilters.arr);
  const queryString = queryParams.toString();

  const { data: routes, loading, error, refetch } = useApi(
    `/routes${queryString ? `?${queryString}` : ""}`
  );

  // Debounce date filter to prevent API spam
  useEffect(() => {
    const timer = setTimeout(() => {
      setAppliedFilters(filters);
      setIsTyping(false);
    }, 500);
    return () => clearTimeout(timer);
  }, [filters.flight_date]);

  // Apply dep/arr filters immediately
  useEffect(() => {
    setAppliedFilters(prev => ({
      ...prev,
      dep: filters.dep,
      arr: filters.arr,
    }));
  }, [filters.dep, filters.arr]);

  const setFilter = (key, val) => {
    setFilters(prev => ({ ...prev, [key]: val }));
    if (key === "flight_date") setIsTyping(true);
  };

  const handleReset = () => {
    setFilters({ dep: "", arr: "", flight_date: today });
    setAppliedFilters({ dep: "", arr: "", flight_date: today });
  };

  if (loading && !routes) return <Spinner />;
  if (error) return <div style={{ padding: 16 }}><ErrorBox msg={error} onRetry={refetch} /></div>;

  return (
    <div style={{ flex: 1, overflow: "auto", padding: "20px 24px", display: "flex", flexDirection: "column", gap: 20, background: "transparent" }}>
      
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <h2 style={{ fontSize: 20, fontWeight: 700, color: "var(--color-text-primary)" }}>Phân tích chặng bay (Route Analytics)</h2>
          <p style={{ fontSize: 12, color: "var(--color-text-secondary)", marginTop: 2 }}>
            Thống kê hiệu năng các chặng bay, tiềm năng tối ưu hóa doanh thu và đối sánh giá vé của AI.
          </p>
        </div>
      </div>

      {/* Filter bar */}
      <div className="glass-panel" style={{
        borderRadius: 14,
        padding: "12px 16px",
        display: "flex",
        gap: 12,
        alignItems: "flex-end",
        flexWrap: "wrap",
      }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 140 }}>
          <label style={{ fontSize: 10, color: "var(--color-text-secondary)", textTransform: "uppercase", fontWeight: 600, letterSpacing: ".05em", display: "flex", alignItems: "center", gap: 4 }}>
            <IconMapPin /> Sân bay đi
          </label>
          <select
            value={filters.dep}
            onChange={e => setFilter("dep", e.target.value)}
            className="glass-input"
            style={{ padding: "8px 12px", fontSize: 12, fontWeight: 500 }}
          >
            <option value="">Tất cả</option>
            {(airports?.departures || []).map(d => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 140 }}>
          <label style={{ fontSize: 10, color: "var(--color-text-secondary)", textTransform: "uppercase", fontWeight: 600, letterSpacing: ".05em", display: "flex", alignItems: "center", gap: 4 }}>
            <IconMapPin /> Sân bay đến
          </label>
          <select
            value={filters.arr}
            onChange={e => setFilter("arr", e.target.value)}
            className="glass-input"
            style={{ padding: "8px 12px", fontSize: 12, fontWeight: 500 }}
          >
            <option value="">Tất cả</option>
            {(airports?.arrivals || []).map(a => (
              <option key={a} value={a}>{a}</option>
            ))}
          </select>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 150 }}>
          <label style={{ fontSize: 10, color: "var(--color-text-secondary)", textTransform: "uppercase", fontWeight: 600, letterSpacing: ".05em", display: "flex", alignItems: "center", gap: 4 }}>
            <IconCalendar /> Ngày bay {isTyping && <span style={{ fontSize: 8 }}>(...)</span>}
          </label>
          <input
            type="date"
            value={filters.flight_date}
            onChange={e => setFilter("flight_date", e.target.value)}
            className="glass-input"
            style={{ padding: "8px 12px", fontSize: 12, fontWeight: 500 }}
          />
        </div>
        <div style={{ flex: 1 }} />
        <button onClick={handleReset}
          className="glass-button"
          style={{
            padding: "8px 16px", borderRadius: 8,
            fontSize: 12, cursor: "pointer",
            display: "flex", alignItems: "center", gap: 6, height: 36
          }}>
          <IconRefresh /> Reset
        </button>
      </div>

      {/* Loading overlay for metrics change */}
      {loading && routes && (
        <div style={{ fontSize: 11, color: "var(--color-text-secondary)", textAlign: "center" }}>
          Đang cập nhật phân tích...
        </div>
      )}

      {/* Empty state */}
      {!loading && routes && routes.length === 0 && (
        <div className="glass-panel" style={{
          borderRadius: 16,
          padding: 40,
          textAlign: "center",
          color: "var(--color-text-secondary)",
          fontSize: 13,
          flex: 1,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 10
        }}>
          <span style={{ color: "var(--color-text-secondary)", display: "flex" }}><IconPlane /></span>
          <div>Không tìm thấy dữ liệu chặng bay nào cho ngày bay đã chọn.</div>
        </div>
      )}

      {/* Metrics List & Chart */}
      {!loading && routes && routes.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 20, flex: 1 }}>
          
          {/* Grid of Route Cards (Glassmorphism layout) */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 14 }}>
            {routes.map(r => {
              const hasUplift = r.revenue_delta_pct > 0;
              const hasDiscount = r.price_change_pct < 0;

              return (
                <div key={r.route} className="glass-panel glass-panel-hover" style={{
                  borderRadius: 14,
                  padding: "14px 18px",
                  display: "flex",
                  flexDirection: "column",
                  gap: 10,
                }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span style={{ fontFamily: "var(--font-mono)", fontWeight: 700, color: "var(--color-text-primary)", fontSize: 14 }}>
                      {r.route}
                    </span>
                    <span style={{ fontSize: 10, background: "var(--color-background-info)", color: "var(--color-text-info)", padding: "2px 8px", borderRadius: 20, fontWeight: 700 }}>
                      {r.count} chuyến
                    </span>
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                    <div>
                      <span style={{ fontSize: 9, color: "var(--color-text-secondary)", textTransform: "uppercase" }}>Giá TB thực tế</span>
                      <div style={{ fontSize: 13, fontWeight: 700, fontFamily: "var(--font-mono)", color: "var(--color-text-secondary)" }}>
                        {fmt(r.avg_price)}
                      </div>
                    </div>
                    <div>
                      <span style={{ fontSize: 9, color: "var(--color-text-info)", textTransform: "uppercase" }}>Giá TB Tối ưu AI</span>
                      <div style={{ fontSize: 13, fontWeight: 700, fontFamily: "var(--font-mono)", color: "var(--color-text-info)" }}>
                        {fmt(r.optimal_price)}
                      </div>
                    </div>
                  </div>

                  {/* Bullet progress bar for load factor */}
                  <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: "var(--color-text-secondary)" }}>
                      <span>Load Factor TB</span>
                      <span style={{ fontWeight: 600 }}>{Math.round(r.avg_lf * 100)}%</span>
                    </div>
                    <div style={{ height: 5, background: "var(--color-border-tertiary)", borderRadius: 2.5, overflow: "hidden" }}>
                      <div style={{
                        width: Math.round(r.avg_lf * 100) + "%",
                        height: "100%",
                        background: getLFColor(r.avg_lf),
                        borderRadius: 2.5
                      }} />
                    </div>
                  </div>

                  {/* Comparison pill details */}
                  <div style={{
                    borderTop: "0.5px solid var(--color-border-tertiary)",
                    paddingTop: 8,
                    marginTop: 2,
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center"
                  }}>
                    <span style={{
                      fontSize: 10,
                      fontWeight: 600,
                      color: hasDiscount ? "var(--color-text-success)" : "var(--color-text-danger)",
                      display: "flex",
                      alignItems: "center",
                      gap: 2
                    }}>
                      {hasDiscount ? <IconChevronDown /> : <IconChevronUp />}
                      Khuyên: {r.price_change_pct >= 0 ? "+" : ""}{r.price_change_pct}%
                    </span>
                    <span style={{
                      fontSize: 10,
                      fontWeight: 700,
                      color: hasUplift ? "var(--color-text-success)" : "var(--color-text-secondary)",
                      background: hasUplift ? "var(--color-background-success)" : "transparent",
                      padding: hasUplift ? "2px 6px" : "0",
                      borderRadius: 6
                    }}>
                      {hasUplift ? `+${r.revenue_delta_pct}% uplift` : "Tối ưu"}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Double Column Comparison BarChart */}
          <div className="glass-panel" style={{
            borderRadius: 16,
            padding: "16px 20px",
            display: "flex",
            flexDirection: "column",
            flex: 1
          }}>
            <h3 style={{ fontSize: 13, fontWeight: 700, color: "var(--color-text-primary)", marginBottom: 4, textTransform: "uppercase" }}>
              So sánh giá thực tế và giá tối ưu AI cho các chặng bay
            </h3>
            <p style={{ fontSize: 11, color: "var(--color-text-secondary)", marginBottom: 16 }}>
              So sánh trực tiếp giá vé trung bình thực tế và giá tối ưu khuyến nghị bởi scipy demand elasticity.
            </p>
            <div style={{ flex: 1, minHeight: 220 }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={routes} margin={{ left: 10, right: 10, top: 10, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-tertiary)" vertical={false} />
                  <XAxis dataKey="route" tick={{ fontSize: 10, fill: "var(--color-text-secondary)" }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: "var(--color-text-secondary)" }} axisLine={false} tickLine={false} tickFormatter={v => (v / 1e6).toFixed(1) + "M"} />
                  <Tooltip contentStyle={{ background: "var(--color-background-primary)", border: "0.5px solid var(--color-border-tertiary)", borderRadius: 8, fontSize: 11 }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Bar dataKey="avg_price" name="Giá thực tế TB" fill="#94a3b8" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="optimal_price" name="Giá tối ưu gợi ý AI" fill="var(--color-text-info)" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

        </div>
      )}
    </div>
  );
}
