import { useState, useCallback, useEffect } from "react";
import { useApi } from "../hooks/useApi";
import { fmt, fmtPct } from "../utils/formatters";
import { Spinner } from "../components/Spinner";
import { IconMapPin, IconCalendar, IconRefresh, IconChevronUp, IconChevronDown, IconUsers, IconDollar, IconPlane, IconTrendUp } from "../components/icons";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ReferenceLine, ResponsiveContainer
} from "recharts";

import { API_BASE_URL as API } from "../config";

export function SimulatorPage() {
  const today = new Date().toISOString().split("T")[0];
  const [filters, setFilters] = useState({
    dep: "", arr: "", flight_date: today,
  });
  const [appliedFilters, setAppliedFilters] = useState(filters);
  const [isTyping, setIsTyping] = useState(false);

  // Get airports list
  const { data: airports } = useApi("/airports");

  // Build query string from filters
  const queryParams = new URLSearchParams();
  if (appliedFilters.flight_date) queryParams.set("flight_date", appliedFilters.flight_date);
  if (appliedFilters.dep) queryParams.set("dep", appliedFilters.dep);
  if (appliedFilters.arr) queryParams.set("arr", appliedFilters.arr);
  const queryString = queryParams.toString();

  const { data: routes } = useApi(`/routes${queryString ? `?${queryString}` : ""}`);
  const [simRoute, setSimRoute] = useState(null);
  
  // What-If Sliders
  const [pct, setPct] = useState(0);         // Price change percentage
  const [lfPct, setLfPct] = useState(70);    // Load factor percentage
  const [simData, setSimData] = useState(null);
  const [loading, setLoading] = useState(false);

  const loadSim = useCallback(async (route, targetLf) => {
    if (!route) return;
    setLoading(true);
    try {
      const res = await fetch(`${API}/simulate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          base_price: route.avg_price,
          base_lf: targetLf / 100,
          capacity: 230,
          from_pct: -30,
          to_pct: 50
        }),
      });
      if (res.ok) {
        setSimData(await res.json());
      }
    } catch (e) {
      console.error("Simulation load failed:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  // Debounce date filter to prevent API spam
  useEffect(() => {
    const timer = setTimeout(() => {
      setAppliedFilters(prev => ({ ...prev, flight_date: filters.flight_date }));
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

  // Clear simulation when routes change and no data exists
  useEffect(() => {
    if (routes && routes.length === 0) {
      setSimRoute(null);
      setSimData(null);
    }
  }, [routes]);

  // Handle route change
  useEffect(() => {
    if (routes && routes.length > 0) {
      const existingRoute = routes.find(r => r.route === simRoute?.route);
      if (!existingRoute) {
        const firstRoute = routes[0];
        setSimRoute(firstRoute);
        setPct(0);
        const initLf = Math.round(firstRoute.avg_lf * 100);
        setLfPct(initLf);
        loadSim(firstRoute, initLf);
      }
    } else if (routes && routes.length === 0) {
      setSimRoute(null);
      setSimData(null);
    }
  }, [routes]);

  const currentPoint = simData?.find(d => Math.abs(d.price_change_pct - pct) <= 2.6);
  const optPoint = simData?.reduce((best, d) =>
    d.revenue_delta_pct > (best?.revenue_delta_pct ?? -Infinity) ? d : best, null);

  // Trigger loadSim when lfPct changes (debounced)
  useEffect(() => {
    if (simRoute && lfPct > 0) {
      const timer = setTimeout(() => {
        loadSim(simRoute, lfPct);
      }, 300);
      return () => clearTimeout(timer);
    }
  }, [lfPct, simRoute, loadSim]);

  // Revenue values calculation
  const baseRevenue = simRoute ? (simRoute.avg_price * 230 * simRoute.avg_lf) : 0;
  const simPriceVal = simRoute ? Math.round(simRoute.avg_price * (1 + pct / 100)) : 0;
  const simLfVal = currentPoint ? currentPoint.new_lf : (lfPct / 100);
  const simulatedRevenue = simPriceVal * 230 * simLfVal;
  const revDeltaPct = baseRevenue > 0 ? ((simulatedRevenue - baseRevenue) / baseRevenue * 100) : 0;

  // Process data points for simple VND chart mapping
  const chartData = (simData || []).map(d => {
    const priceVal = simRoute ? Math.round(simRoute.avg_price * (1 + d.price_change_pct / 100)) : 0;
    return {
      ...d,
      price_val: priceVal,
      revenue_vnd: Math.round(priceVal * 230 * d.new_lf)
    };
  });

  const optPriceVal = (simRoute && optPoint) ? Math.round(simRoute.avg_price * (1 + optPoint.price_change_pct / 100)) : 0;

  return (
    <div style={{ flex: 1, overflow: "auto", padding: "20px 24px", display: "flex", flexDirection: "column", gap: 20, background: "transparent" }}>
      
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <h2 style={{ fontSize: 20, fontWeight: 700, color: "var(--color-text-primary)" }}>Giả lập doanh thu</h2>
          <span style={{ background: "var(--color-background-warning)", color: "var(--color-text-warning)", padding: "2.5px 10px", borderRadius: 20, fontSize: 10, fontWeight: 700, textTransform: "uppercase" }}>
            What-if Sandbox
          </span>
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
            style={{ padding: "8px 12px", fontSize: 12, fontWeight: 500, outline: "none" }}
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
            style={{ padding: "8px 12px", fontSize: 12, fontWeight: 500, outline: "none" }}
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
            style={{ padding: "8px 12px", fontSize: 12, fontWeight: 500, outline: "none" }}
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

      {/* Main Workspace */}
      {!routes ? (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", flex: 1, minHeight: 300 }}>
          <Spinner />
        </div>
      ) : routes.length === 0 ? (
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
          <span style={{ color: "var(--color-text-secondary)" }}><IconPlane /></span>
          <div>Không có lịch trình bay nào khớp với bộ lọc.</div>
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1.2fr", gap: 20, alignItems: "stretch", flex: 1 }}>
          
          {/* LEFT: Controls and metrics */}
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            
            {/* Route Selector Dropdown */}
            <div className="glass-panel" style={{
              borderRadius: 14,
              padding: "16px 20px",
              display: "flex",
              flexDirection: "column",
              gap: 12
            }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <label style={{ fontSize: 10, color: "var(--color-text-secondary)", textTransform: "uppercase", fontWeight: 700, letterSpacing: ".05em" }}>
                  Chặng bay hoạt động chọn lọc
                </label>
                <select
                  value={simRoute?.route || ""}
                  onChange={e => {
                    const r = routes.find(x => x.route === e.target.value);
                    if (r) {
                      setSimRoute(r);
                      setPct(0);
                      setLfPct(Math.round(r.avg_lf * 100));
                      loadSim(r, Math.round(r.avg_lf * 100));
                    }
                  }}
                  className="glass-input"
                  style={{
                    padding: "8px 12px",
                    fontSize: 12,
                    fontWeight: 600,
                    cursor: "pointer",
                    outline: "none"
                  }}
                >
                  {routes.map(r => (
                    <option key={r.route} value={r.route}>
                      Tuyến: {r.route} ({r.count} chuyến trong ngày)
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* Sliders sandbox */}
            {simRoute && (
              <div className="glass-panel" style={{
                borderRadius: 14,
                padding: "16px 20px",
                display: "flex",
                flexDirection: "column",
                gap: 16,
              }}>
                <span style={{ fontSize: 10, color: "var(--color-text-secondary)", textTransform: "uppercase", fontWeight: 700 }}>Điều chỉnh thông số giả lập</span>
                
                {/* Price slider */}
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
                    <span style={{ color: "var(--color-text-primary)", fontWeight: 500 }}>Thay đổi giá bán vé (%):</span>
                    <span style={{ fontWeight: 700, fontFamily: "var(--font-mono)", color: pct > 0 ? "var(--color-text-danger)" : pct < 0 ? "var(--color-text-success)" : "var(--color-text-primary)" }}>
                      {pct >= 0 ? "+" : ""}{pct}%
                    </span>
                  </div>
                  <input type="range" min={-30} max={50} step={1} value={pct} onChange={e => setPct(+e.target.value)} style={{ height: 6, margin: "6px 0" }} />
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: "var(--color-text-secondary)" }}>
                    <span>Giảm -30%</span><span>Giá gốc (0)</span><span>Tăng +50%</span>
                  </div>
                </div>

                {/* Load factor slider */}
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
                    <span style={{ color: "var(--color-text-primary)", fontWeight: 500 }}>Tỷ lệ lấp đầy cơ sở (Base LF %):</span>
                    <span style={{ fontWeight: 700, fontFamily: "var(--font-mono)", color: "var(--color-text-info)" }}>
                      {lfPct}%
                    </span>
                  </div>
                  <input type="range" min={10} max={100} step={1} value={lfPct} onChange={e => setLfPct(+e.target.value)} style={{ height: 6, margin: "6px 0" }} />
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: "var(--color-text-secondary)" }}>
                    <span>10% LF</span><span>Gốc ({Math.round(simRoute.avg_lf * 100)}%)</span><span>100% LF</span>
                  </div>
                </div>
              </div>
            )}

            {/* Metrics Grid */}
            {simRoute && (
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                <div className="glass-panel" style={{ borderRadius: 12, padding: "12px 14px" }}>
                  <div style={{ fontSize: 9, color: "var(--color-text-secondary)", textTransform: "uppercase", fontWeight: 700 }}>Doanh thu cơ sở</div>
                  <div style={{ fontSize: 16, fontWeight: 700, fontFamily: "var(--font-mono)", color: "var(--color-text-primary)", marginTop: 4 }}>
                    {fmt(Math.round(baseRevenue))}đ
                  </div>
                </div>

                <div className="glass-panel" style={{ borderRadius: 12, padding: "12px 14px" }}>
                  <div style={{ fontSize: 9, color: "var(--color-text-secondary)", textTransform: "uppercase", fontWeight: 700 }}>Tỷ lệ doanh thu mới</div>
                  <div style={{ fontSize: 16, fontWeight: 700, fontFamily: "var(--font-mono)", color: revDeltaPct >= 0 ? "var(--color-text-success)" : "var(--color-text-danger)", marginTop: 4 }}>
                    {revDeltaPct >= 0 ? `+${revDeltaPct.toFixed(2)}%` : `${revDeltaPct.toFixed(2)}%`}
                  </div>
                </div>

                <div className="glass-panel" style={{ borderRadius: 12, padding: "12px 14px" }}>
                  <div style={{ fontSize: 9, color: "var(--color-text-secondary)", textTransform: "uppercase", fontWeight: 700 }}>Giá vé giả lập tương ứng</div>
                  <div style={{ fontSize: 16, fontWeight: 700, fontFamily: "var(--font-mono)", color: "var(--color-text-primary)", marginTop: 4 }}>
                    {fmt(simPriceVal)}đ
                  </div>
                </div>

                <div className="glass-panel" style={{ borderRadius: 12, padding: "12px 14px" }}>
                  <div style={{ fontSize: 9, color: "var(--color-text-secondary)", textTransform: "uppercase", fontWeight: 700 }}>Dự kiến lấp đầy tương ứng</div>
                  <div style={{ fontSize: 16, fontWeight: 700, fontFamily: "var(--font-mono)", color: "var(--color-text-info)", marginTop: 4 }}>
                    {Math.round(simLfVal * 100)}%
                  </div>
                </div>
              </div>
            )}

            {/* Optimal reference target details */}
            {simRoute && optPoint && (
              <div style={{
                background: "var(--color-background-success)",
                borderRadius: 12,
                padding: "12px 16px",
                border: "1.5px solid var(--color-border-success)",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center"
              }}>
                <div>
                  <div style={{ fontSize: 10, color: "var(--color-text-success)", fontWeight: 700, textTransform: "uppercase", display: "flex", alignItems: "center", gap: 4 }}>
                    <IconTrendUp /> Gợi ý giá trị tối ưu doanh thu
                  </div>
                  <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginTop: 4 }}>
                    Thiết lập giá: <strong>{fmt(Math.round(simRoute.avg_price * (1 + optPoint.price_change_pct / 100)))}đ</strong> ({optPoint.price_change_pct >= 0 ? "+" : ""}{optPoint.price_change_pct}%)
                  </div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <div style={{ fontSize: 18, fontWeight: 800, color: "var(--color-text-success)", fontFamily: "var(--font-mono)" }}>
                    +{optPoint.revenue_delta_pct.toFixed(1)}%
                  </div>
                  <span style={{ fontSize: 8, color: "var(--color-text-success)", textTransform: "uppercase" }}>Tăng trưởng doanh thu</span>
                </div>
              </div>
            )}

          </div>

          {/* RIGHT: Simplified Revenue Simulator Chart */}
          <div className="glass-panel" style={{
            borderRadius: 16,
            padding: "16px 20px",
            display: "flex",
            flexDirection: "column",
          }}>
            {simRoute ? (
              <>
                <h3 style={{ fontSize: 14, fontWeight: 700, color: "var(--color-text-primary)" }}>Dự toán tổng doanh thu (VND) theo giá vé</h3>
                <p style={{ fontSize: 11, color: "var(--color-text-secondary)", marginBottom: 12 }}>
                  Tuyến: {simRoute.route} | Giá gốc trung bình: {fmt(simRoute.avg_price)}đ | LF gốc: {Math.round(simRoute.avg_lf * 100)}%
                </p>

                {loading ? (
                  <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}><Spinner /></div>
                ) : simData ? (
                  <div style={{ flex: 1, minHeight: 280, display: "flex", flexDirection: "column" }}>
                    <div style={{ flex: 1 }}>
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={chartData} margin={{ left: 10, right: 10, top: 10, bottom: 5 }}>
                          <defs>
                            <linearGradient id="colorSimRev" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%" stopColor="var(--color-border-info)" stopOpacity={0.4}/>
                              <stop offset="95%" stopColor="var(--color-border-info)" stopOpacity={0}/>
                            </linearGradient>
                          </defs>
                          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-tertiary)" vertical={false} />
                          <XAxis dataKey="price_val" tick={{ fontSize: 9, fill: "var(--color-text-secondary)" }} tickFormatter={v => (v / 1e3).toFixed(0) + "kđ"} axisLine={false} tickLine={false} />
                          <YAxis tick={{ fontSize: 9, fill: "var(--color-text-secondary)" }} axisLine={false} tickLine={false} tickFormatter={v => (v / 1e6).toFixed(0) + "M"} />
                          
                          <Tooltip formatter={(value) => [fmt(value) + "đ", "Doanh thu"]} labelFormatter={(label) => `Giá vé: ${fmt(label)}đ`} contentStyle={{ background: "var(--color-background-primary)", border: "0.5px solid var(--color-border-tertiary)", borderRadius: 8, fontSize: 11 }} />
                          
                          {/* Reference vertical lines for Current and Optimal prices */}
                          <ReferenceLine x={simPriceVal} stroke="var(--color-border-info)" strokeWidth={2} label={{ value: "Hiện tại", fill: "var(--color-text-info)", fontSize: 9, position: "top", fontWeight: 700 }} />
                          {optPoint && optPriceVal > 0 && (
                            <ReferenceLine x={optPriceVal} stroke="var(--color-border-success)" strokeWidth={2} strokeDasharray="4 3" label={{ value: "Tối ưu AI", fill: "var(--color-text-success)", fontSize: 9, position: "top", fontWeight: 700 }} />
                          )}
                          
                          <Area type="monotone" dataKey="revenue_vnd" name="Doanh thu giả định (VND)" stroke="var(--color-border-info)" strokeWidth={3} fillOpacity={1} fill="url(#colorSimRev)" />
                        </AreaChart>
                      </ResponsiveContainer>
                    </div>
                    
                    <div style={{ display: "flex", justifyContent: "center", gap: 16, marginTop: 10, fontSize: 10, color: "var(--color-text-secondary)" }}>
                      <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                        <span style={{ width: 12, height: 3, background: "var(--color-border-info)", display: "inline-block" }} />
                        Đường cong Doanh thu (VND)
                      </span>
                      <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                        <span style={{ width: 1, height: 10, borderLeft: "2px solid var(--color-border-info)", display: "inline-block" }} />
                        Mức giá vé đang thử nghiệm
                      </span>
                      <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                        <span style={{ width: 1, height: 10, borderLeft: "2px dashed var(--color-border-success)", display: "inline-block" }} />
                        Mức giá vé tối ưu AI khuyên dùng
                      </span>
                    </div>
                  </div>
                ) : (
                  <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--color-text-secondary)", fontSize: 11 }}>
                    Chưa có dữ liệu đồ thị
                  </div>
                )}
              </>
            ) : (
              <div style={{ display: "flex", alignItems: "center", justifyContent: "center", flex: 1, color: "var(--color-text-secondary)", fontSize: 12 }}>
                Vui lòng chọn chặng bay để xem đồ thị giả lập.
              </div>
            )}
          </div>

        </div>
      )}
    </div>
  );
}
