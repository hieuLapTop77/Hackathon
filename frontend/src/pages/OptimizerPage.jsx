import { useState, useEffect, useCallback, useRef } from "react";
import { useApi } from "../hooks/useApi";
import { fmt, fmtPct } from "../utils/formatters";
import { Spinner } from "../components/Spinner";
import { Pagination } from "../components/Pagination";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  BarChart, Bar, Cell
} from "recharts";
import {
  IconCheck, IconWarning, IconChevronUp, IconChevronDown,
  IconArrowRight, IconDollar, IconUsers, IconSearch,
  IconRefresh, IconMapPin, IconCalendar, IconSort, IconSparkles, IconPlane
} from "../components/icons";

import { API_BASE_URL as API } from "../config";
const PAGE_SIZE = 15;
const DEFAULT_CAPACITY = 230;

const CLASS_COLORS = {
  "Eco": "#10b981",      // Green
  "Deluxe": "#f59e0b",   // Orange
  "SkyBoss": "#8b5cf6",  // Purple
  "GDS": "#3b82f6",      // Blue
  "Business": "#3b82f6"  // Blue (mapped to Business in DB)
};

export function OptimizerPage({ selectedFlight, onApplySuccess }) {
  const today = new Date().toISOString().split("T")[0];

  // Top filters for available flights list
  const [filters, setFilters] = useState({
    dep: "", arr: "", flight_date: "", sort_by: "flight_date", sort_dir: "asc",
  });
  const [flights, setFlights] = useState([]);
  const [flLoading, setFlLoading] = useState(false);
  const [flError, setFlError] = useState(null);
  const [page, setPage] = useState(1);
  const [totalCount, setTotalCount] = useState(0);

  const { data: dbRoutes } = useApi("/db/routes");
  const { data: modelsData } = useApi("/models");

  // State for active flight under optimization
  const [curFlight, setCurFlight] = useState(null);
  // All fare classes (rows) for the active flight
  const [fareFamilies, setFareFamilies] = useState([]);
  const [famLoading, setFamLoading] = useState(false);

  // Model filter selection
  const [selectedModelName, setSelectedModelName] = useState("");
  // Batch predictions for all families
  const [aiPredictions, setAiPredictions] = useState({});
  const [aiLoading, setAiLoading] = useState(false);

  // Focused fare family for What-If sandbox (right pane)
  const [focusedFamId, setFocusedFamId] = useState(null);

  // Local editing states (keys are row IDs)
  const [editedPrices, setEditedPrices] = useState({});
  const [editedLfs, setEditedLfs] = useState({});

  // Optimization & simulation results for focused class
  const [optResult, setOptResult] = useState(null);
  const [simData, setSimData] = useState([]);
  const [optLoading, setOptLoading] = useState(false);
  const [simChartLoading, setSimChartLoading] = useState(false);
  const [applyStatus, setApplyStatus] = useState(null); // null | 'saving' | 'ok' | 'error'
  const [competitorPrices, setCompetitorPrices] = useState([]);
  const [compLoading, setCompLoading] = useState(false);

  const optDebounceRef = useRef(null);

  const setFilter = (key, val) => {
    setFilters(prev => ({ ...prev, [key]: val }));
    setPage(1);
  };

  const buildQs = () => {
    const p = new URLSearchParams();
    if (filters.dep) p.set("dep", filters.dep);
    if (filters.arr) p.set("arr", filters.arr);
    if (filters.flight_date) p.set("flight_date", filters.flight_date);
    if (filters.sort_by) p.set("sort_by", filters.sort_by);
    if (filters.sort_dir) p.set("sort_dir", filters.sort_dir);
    p.set("page", page);
    p.set("page_size", PAGE_SIZE);
    return p.toString();
  };

  // Fetch available flights list based on search filters
  const fetchFlightsList = async () => {
    setFlLoading(true);
    setFlError(null);
    try {
      const res = await fetch(`${API}/flights?${buildQs()}`);
      if (!res.ok) throw new Error(`API error ${res.status}`);
      const data = await res.json();
      const list = Array.isArray(data) ? data : (data.items || []);
      setFlights(list);
      setTotalCount(data.total ?? list.length);
    } catch (e) {
      setFlError(e.message);
    } finally {
      setFlLoading(false);
    }
  };

  useEffect(() => {
    fetchFlightsList();
  }, [filters.dep, filters.arr, filters.flight_date, filters.sort_by, filters.sort_dir, page]);

  const handleSortChange = (label, direction) => {
    const map = { "Ngày bay": "flight_date", "Giá hiện tại": "price", "LF": "lf", "Tuyến": "route" };
    setFilters(prev => ({
      ...prev,
      sort_by: map[label] || label,
      sort_dir: direction
    }));
    setPage(1);
  };

  const handleReset = () => {
    setFilters({ dep: "", arr: "", flight_date: "", sort_by: "flight_date", sort_dir: "asc" });
    setPage(1);
  };

  // Initialize selected model from models list
  useEffect(() => {
    if (modelsData?.models?.length > 0) {
      const best = modelsData.models.find(m => m.best);
      setSelectedModelName(best ? best.name : modelsData.models[0].name);
    }
  }, [modelsData]);

  // Set current active flight when selected from parent component
  useEffect(() => {
    if (selectedFlight) {
      setCurFlight(selectedFlight);
    }
  }, [selectedFlight]);

  // Fetch all 4 fare families belonging to the active flight (same route & date)
  useEffect(() => {
    if (!curFlight) return;
    setFamLoading(true);
    const [depVal, arrVal] = (curFlight.route || "").split("->").map(s => s.trim());
    fetch(`${API}/flights?dep=${depVal || curFlight.dep}&arr=${arrVal || curFlight.arr}&flight_date=${curFlight.flight_date}&page_size=100`)
      .then(res => res.json())
      .then(data => {
        const list = Array.isArray(data) ? data : (data.items || []);
        setFareFamilies(list);
        
        // Reset edits to fresh database values
        const prices = {};
        const lfs = {};
        list.forEach(f => {
          prices[f.id] = f.price;
          lfs[f.id] = f.lf;
        });
        setEditedPrices(prices);
        setEditedLfs(lfs);

        // Auto focus on the row matching curFlight ID, or the first family
        const match = list.find(x => x.id === curFlight.id) || list[0];
        if (match) {
          setFocusedFamId(match.id);
        } else if (list.length > 0) {
          setFocusedFamId(list[0].id);
        }
      })
      .catch(err => console.error("Error loading fare families for flight:", err))
      .finally(() => setFamLoading(false));
  }, [curFlight]);

  // Batch predict AI Suggested prices for all 4 classes whenever families or model selection changes
  useEffect(() => {
    if (!fareFamilies || fareFamilies.length === 0 || !selectedModelName) {
      setAiPredictions({});
      return;
    }

    const controller = new AbortController();
    const runPredict = async () => {
      setAiLoading(true);
      try {
        const payload = {
          model_name: selectedModelName,
          flights: fareFamilies.map(f => {
            const [depVal, arrVal] = (f.route || "").split("->").map(s => s.trim());
            return {
              id: f.id,
              lead_time_days: f.lead_time_days ?? 30,
              LF_by_date: f.lf ?? 0.65,
              LF_by_fare: f.LF_by_fare ?? f.lf ?? 0.40,
              booking_velocity_3d: f.booking_velocity_3d ?? 0.02,
              booking_velocity_7d: f.booking_velocity_7d ?? 0.05,
              Weekday: f.Weekday ?? 4,
              IsHoliday: f.IsHoliday ?? 0,
              is_oneway: f.is_oneway ?? 1,
              lng_fuel: f.lng_fuel ?? 93.86,
              capacity: f.capacity ?? f.lng_Capacity ?? DEFAULT_CAPACITY,
              count_sked: f.count_sked ?? 3,
              fare_family: f.fare_family || "Eco",
              fare_category: f.fare_category || f.str_Fare_Category || "B",
              dep: depVal || f.str_Dep || "SGN",
              arr: arrVal || f.str_Arr || "HAN",
              current_price: f.price ?? null,
            };
          })
        };

        const res = await fetch(`${API}/predict-for-flights`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          signal: controller.signal
        });
        if (res.ok) {
          const data = await res.json();
          setAiPredictions(data.predictions || {});
        }
      } catch (err) {
        if (err.name !== "AbortError") {
          console.error("Optimizer batch predict failed:", err);
        }
      } finally {
        setAiLoading(false);
      }
    };

    runPredict();
    return () => controller.abort();
  }, [fareFamilies, selectedModelName]);

  // Resolve AI Suggested price for a specific row
  const getAiSuggestedPrice = (f) => {
    const uiClass = f.fare_family === "Business" ? "GDS" : f.fare_family;
    if (selectedModelName && aiPredictions[f.id]) {
      const predVal = aiPredictions[f.id][uiClass]?.predicted_price_vnd;
      if (predVal != null) return predVal;
    }
    // Fallback to pre-calculated suggestions in database row
    return f.ai_suggestions?.[uiClass] || f.optimal_price || f.price;
  };

  // Focused fare family row object
  const focusedFam = fareFamilies.find(f => f.id === focusedFamId);

  // Call scipy optimize and simulate endpoints for focused family (debounced)
  const callOptimizeAndSimulate = useCallback(async (basePrice, baseLf) => {
    setOptLoading(true);
    setSimChartLoading(true);
    try {
      const optPromise = fetch(`${API}/optimize`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ base_price: basePrice, base_lf: baseLf / 100, capacity: DEFAULT_CAPACITY }),
      }).then(r => r.json());

      const simPromise = fetch(`${API}/simulate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          base_price: basePrice,
          base_lf: baseLf / 100,
          capacity: DEFAULT_CAPACITY,
          from_pct: -30,
          to_pct: 50
        }),
      }).then(r => r.json());

      const [optData, simDataPoints] = await Promise.all([optPromise, simPromise]);
      setOptResult(optData);
      setSimData(simDataPoints);
    } catch (e) {
      console.error("Optimize/Simulate endpoints failed:", e);
    } finally {
      setOptLoading(false);
      setSimChartLoading(false);
    }
  }, []);

  // Sync right-pane simulator inputs when active focused class changes
  useEffect(() => {
    if (focusedFam) {
      const currentPrice = editedPrices[focusedFam.id] ?? focusedFam.price;
      const currentLfPct = Math.round((editedLfs[focusedFam.id] ?? focusedFam.lf) * 100);
      callOptimizeAndSimulate(currentPrice, currentLfPct);
    } else {
      setOptResult(null);
      setSimData([]);
    }
  }, [focusedFamId, curFlight]);

  // Fetch competitor prices dynamically when active class or price updates
  useEffect(() => {
    if (!focusedFam || !curFlight) return;
    const [depVal, arrVal] = (curFlight.route || "").split("->").map(s => s.trim());
    const routeVal = `${depVal || curFlight.dep}-${arrVal || curFlight.arr}`;
    const priceVal = editedPrices[focusedFam.id] ?? focusedFam.price;
    const uiClass = focusedFam.fare_family === "Business" ? "GDS" : focusedFam.fare_family;
    
    setCompLoading(true);
    
    fetch(`${API}/competitor-prices?route=${routeVal}&base_price=${priceVal}&flight_date=${curFlight.flight_date}&fare_class=${uiClass}`)
      .then(res => res.json())
      .then(data => {
        if (Array.isArray(data)) {
          setCompetitorPrices(data);
        } else {
          setCompetitorPrices([]);
        }
      })
      .catch(err => {
        console.error("Error loading competitor prices:", err);
        setCompetitorPrices([]);
      })
      .finally(() => setCompLoading(false));
  }, [focusedFamId, curFlight, editedPrices]);

  // Handle What-If sliders updates for focused class
  const handleSandboxChange = (newPrice, newLfPct) => {
    if (!focusedFam) return;
    setEditedPrices(prev => ({ ...prev, [focusedFam.id]: newPrice }));
    setEditedLfs(prev => ({ ...prev, [focusedFam.id]: newLfPct / 100 }));

    clearTimeout(optDebounceRef.current);
    optDebounceRef.current = setTimeout(() => {
      callOptimizeAndSimulate(newPrice, newLfPct);
    }, 400);
  };

  // Copy AI Suggested price to the actual edited state
  const handleApplyAiPrice = (f) => {
    const aiPrice = getAiSuggestedPrice(f);
    if (aiPrice == null) return;
    setEditedPrices(prev => ({ ...prev, [f.id]: aiPrice }));
    // If this is the currently focused class, update optimize/simulate charts too
    if (f.id === focusedFamId) {
      const currentLfPct = Math.round((editedLfs[f.id] ?? f.lf) * 100);
      callOptimizeAndSimulate(aiPrice, currentLfPct);
    }
  };

  // Copy AI Suggested prices to ALL 4 classes at once
  const handleApplyAllAiPrices = () => {
    const newPrices = { ...editedPrices };
    fareFamilies.forEach(f => {
      const aiPrice = getAiSuggestedPrice(f);
      if (aiPrice != null) {
        newPrices[f.id] = aiPrice;
      }
    });
    setEditedPrices(newPrices);

    // Update active optimization details if a focused class is active
    if (focusedFam) {
      const aiPrice = getAiSuggestedPrice(focusedFam);
      if (aiPrice != null) {
        const currentLfPct = Math.round((editedLfs[focusedFam.id] ?? focusedFam.lf) * 100);
        callOptimizeAndSimulate(aiPrice, currentLfPct);
      }
    }
  };

  // Save changes to database
  const handleSaveChanges = async () => {
    if (!curFlight) return;
    setApplyStatus("saving");
    const updates = fareFamilies.map(f => ({
      id: f.id,
      price: editedPrices[f.id] !== undefined ? parseFloat(editedPrices[f.id]) : f.price,
      lf: editedLfs[f.id] !== undefined ? parseFloat(editedLfs[f.id]) : f.lf,
    }));

    try {
      const res = await fetch(`${API}/flights/${curFlight.id}/fares`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ updates }),
      });
      if (res.ok) {
        setApplyStatus("ok");
        onApplySuccess && onApplySuccess();
        setTimeout(() => setApplyStatus(null), 3000);
        
        // Refresh available flights list to pull latest prices
        fetchFlightsList();
      } else {
        throw new Error("Save request failed");
      }
    } catch (e) {
      console.error(e);
      setApplyStatus("error");
      setTimeout(() => setApplyStatus(null), 3000);
    }
  };

  const activeFocusedPrice = focusedFam ? (editedPrices[focusedFam.id] ?? focusedFam.price) : 0;
  const activeFocusedLf = focusedFam ? Math.round((editedLfs[focusedFam.id] ?? focusedFam.lf) * 100) : 0;

  const optColor = optResult
    ? optResult.price_change_pct > 0 ? "var(--color-text-success)"
      : optResult.price_change_pct < 0 ? "var(--color-text-danger)"
      : "var(--color-text-info)"
    : "var(--color-text-primary)";

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

      {/* Header Area */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h2 style={{ fontSize: 22, fontWeight: 800, color: "var(--color-text-primary)", letterSpacing: "-0.5px" }}>Tối ưu hóa giá vé (Price Optimizer)</h2>
          <p style={{ fontSize: 12, color: "var(--color-text-secondary)", marginTop: 2 }}>
            Điều chỉnh giá vé thực tế, tỷ lệ lấp đầy (Load Factor) và đối chiếu với dự báo của mô hình trí tuệ nhân tạo.
          </p>
        </div>
      </div>

      {/* Flight Search Selector Bar */}
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
        <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 130 }}>
          <label style={{ fontSize: 10, color: "var(--color-text-secondary)", textTransform: "uppercase", fontWeight: 700, letterSpacing: ".05em", display: "flex", alignItems: "center", gap: 4 }}>
            <IconMapPin /> Điểm đi
          </label>
          <select 
            value={filters.dep} 
            onChange={e => setFilter("dep", e.target.value)}
            className="glass-input"
            style={{ padding: "8px 12px", fontSize: 12, outline: "none", border: "none", color: "#fff", cursor: "pointer" }}
          >
            <option value="" style={{ background: "#1e293b" }}>Tất cả</option>
            {[...new Set((dbRoutes || []).map(r => r.str_Dep || r.route?.split("-")[0]).filter(Boolean))].map(d => <option key={d} value={d} style={{ background: "#1e293b" }}>{d}</option>)}
          </select>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 130 }}>
          <label style={{ fontSize: 10, color: "var(--color-text-secondary)", textTransform: "uppercase", fontWeight: 700, letterSpacing: ".05em", display: "flex", alignItems: "center", gap: 4 }}>
            <IconMapPin /> Điểm đến
          </label>
          <select 
            value={filters.arr} 
            onChange={e => setFilter("arr", e.target.value)}
            className="glass-input"
            style={{ padding: "8px 12px", fontSize: 12, outline: "none", border: "none", color: "#fff", cursor: "pointer" }}
          >
            <option value="" style={{ background: "#1e293b" }}>Tất cả</option>
            {[...new Set((dbRoutes || []).map(r => r.str_Arr || r.route?.split("-")[1]).filter(Boolean))].map(a => <option key={a} value={a} style={{ background: "#1e293b" }}>{a}</option>)}
          </select>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 140 }}>
          <label style={{ fontSize: 10, color: "var(--color-text-secondary)", textTransform: "uppercase", fontWeight: 700, letterSpacing: ".05em", display: "flex", alignItems: "center", gap: 4 }}>
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

        <div style={{ width: "1px", height: 32, background: "var(--color-border-tertiary)", margin: "0 4px", alignSelf: "center" }} />

        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <label style={{ fontSize: 10, color: "var(--color-text-secondary)", textTransform: "uppercase", fontWeight: 700, letterSpacing: ".05em", display: "flex", alignItems: "center", gap: 4 }}>
            <IconSort /> Sắp xếp
          </label>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {/* Segmented Control / Pill Group */}
            <div style={{
              display: "flex",
              background: "rgba(255, 255, 255, 0.04)",
              padding: 3,
              borderRadius: 10,
              boxShadow: "0 1px 2px rgba(0,0,0,0.15)"
            }}>
              {[
                { label: "Ngày bay", value: "flight_date" },
                { label: "Giá hiện tại", value: "price" },
                { label: "LF", value: "lf" },
                { label: "Tuyến", value: "route" }
              ].map(opt => {
                const isActive = filters.sort_by === opt.value;
                return (
                  <button
                    key={opt.value}
                    onClick={() => setFilter("sort_by", opt.value)}
                    style={{
                      padding: "6px 12px",
                      borderRadius: 8,
                      border: "none",
                      background: isActive ? "var(--color-text-info)" : "transparent",
                      color: isActive ? "#ffffff" : "var(--color-text-secondary)",
                      fontSize: 11,
                      fontWeight: isActive ? 700 : 500,
                      cursor: "pointer",
                      transition: "all 0.2s cubic-bezier(0.16, 1, 0.3, 1)",
                      whiteSpace: "nowrap"
                    }}
                  >
                    {opt.label}
                  </button>
                );
              })}
            </div>

            {/* Direction Toggle Button */}
            <button
              onClick={() => setFilter("sort_dir", filters.sort_dir === "asc" ? "desc" : "asc")}
              title={filters.sort_dir === "asc" ? "Tăng dần (Click để giảm dần)" : "Giảm dần (Click để tăng dần)"}
              className="glass-button"
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                padding: "6px 12px",
                borderRadius: 10,
                color: "var(--color-text-primary)",
                fontSize: 11,
                fontWeight: 600,
                cursor: "pointer",
                height: 30,
              }}
            >
              <span style={{ display: "flex", alignItems: "center", color: "var(--color-text-info)" }}>
                {filters.sort_dir === "asc" ? <IconChevronUp /> : <IconChevronDown />}
              </span>
              <span>{filters.sort_dir === "asc" ? "Tăng dần" : "Giảm dần"}</span>
            </button>
          </div>
        </div>

        <div style={{ flex: 1 }} />

        <button 
          onClick={fetchFlightsList} 
          disabled={flLoading}
          className="glass-button"
          style={{
            padding: "8px 16px", borderRadius: "var(--border-radius-md)", border: "none",
            color: "var(--color-text-info)",
            fontSize: 12, fontWeight: 700, cursor: flLoading ? "not-allowed" : "pointer",
            display: "flex", alignItems: "center", gap: 6, height: 36,
            boxShadow: "0 4px 12px rgba(255, 79, 94, 0.1)"
          }}
        >
          <IconSearch /> {flLoading ? "Tìm kiếm..." : "Tìm chuyến bay"}
        </button>
        <button 
          onClick={handleReset}
          className="glass-button"
          style={{
            padding: "8px 16px", borderRadius: "var(--border-radius-md)",
            color: "var(--color-text-secondary)", fontSize: 12, cursor: "pointer",
            display: "flex", alignItems: "center", gap: 6, height: 36, fontWeight: 600
          }}
        >
          <IconRefresh /> Reset
        </button>
      </div>

      {/* Available Flights Horizontal Picker */}
      <div 
        className="glass-panel"
        style={{
          borderRadius: "var(--border-radius-lg)",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
          flexShrink: 0,
          boxShadow: "0 10px 30px rgba(0,0,0,0.15)"
        }}
      >
        <div style={{ padding: "10px 14px", borderBottom: "1px solid rgba(255,255,255,0.08)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", color: "var(--color-text-secondary)" }}>Lịch trình chuyến bay tìm thấy</span>
          <span style={{ fontSize: 11, background: "var(--color-background-info)", color: "var(--color-text-info)", padding: "2px 8px", borderRadius: 10, fontWeight: 700, border: "1px solid var(--color-border-info)" }}>{totalCount} chuyến</span>
        </div>
        <div style={{ display: "flex", gap: 8, overflowX: "auto", padding: "12px 14px", flexShrink: 0 }}>
          {flLoading && <div style={{ display: "flex", flex: 1, justifyContent: "center", alignItems: "center" }}><Spinner /></div>}
          {!flLoading && flights.length === 0 && (
            <div style={{ width: "100%", textAlign: "center", color: "var(--color-text-secondary)", fontSize: 12, padding: "8px 0" }}>
              Không tìm thấy chuyến bay nào trùng khớp với bộ lọc ngày bay.
            </div>
          )}
          {!flLoading && flights.length > 0 && flights.map(f => (
            <button 
              key={f.id} 
              onClick={() => setCurFlight(f)}
              className={curFlight?.id === f.id ? "nav-active-drop" : "glass-button"}
              style={{
                padding: "8px 14px", borderRadius: 8, border: "none",
                fontSize: 11, cursor: "pointer",
                color: curFlight?.id === f.id ? "var(--color-text-info)" : "var(--color-text-primary)",
                fontFamily: "var(--font-mono)", fontWeight: curFlight?.id === f.id ? 700 : 500,
                boxShadow: "0 2px 4px rgba(0,0,0,0.1)",
                transition: "all .2s cubic-bezier(0.16, 1, 0.3, 1)",
                flexShrink: 0
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <IconPlane />
                <span>{f.flight_no || f.id} ({f.route})</span>
              </div>
            </button>
          ))}
        </div>
        {!flLoading && flights.length > 0 && (
          <div style={{ padding: "8px 14px", borderTop: "1px solid rgba(255,255,255,0.08)", display: "flex", justifyContent: "flex-end", background: "rgba(0,0,0,0.05)" }}>
            <Pagination page={page} total={totalCount} pageSize={PAGE_SIZE} onChange={p => setPage(p)} />
          </div>
        )}
      </div>

      {/* Main Optimization Workspace */}
      {curFlight ? (
        <div style={{ display: "grid", gridTemplateColumns: "1.2fr 0.8fr", gap: 20, alignItems: "stretch", flex: 1 }}>

          {/* LEFT: All 4 classes (Actual vs predicted) */}
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            
            {/* Active Flight Header Details */}
            <div 
              className="glass-panel"
              style={{
                borderRadius: "var(--border-radius-lg)",
                padding: "16px 20px",
                boxShadow: "0 10px 30px rgba(0,0,0,0.15)",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center"
              }}
            >
              <div>
                <div style={{ fontSize: 10, color: "var(--color-text-secondary)", textTransform: "uppercase", fontWeight: 700, letterSpacing: ".05em" }}>Đang điều chỉnh chuyến bay</div>
                <div style={{ fontSize: 18, fontWeight: 800, color: "var(--color-text-primary)", fontFamily: "var(--font-mono)", marginTop: 4, display: "flex", alignItems: "center", gap: 8 }}>
                  <span>{curFlight.flight_no}</span>
                  <span style={{ fontSize: 14, color: "var(--color-text-secondary)", fontWeight: 400 }}>· {curFlight.route} · {curFlight.flight_date}</span>
                </div>
              </div>

              {/* Model selection dropdown inside active workspace */}
              <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 200 }}>
                <span style={{ fontSize: 10, color: "var(--color-text-secondary)", textTransform: "uppercase", fontWeight: 700, letterSpacing: ".05em" }}>
                  Mô hình dự báo AI
                </span>
                <select
                  value={selectedModelName}
                  onChange={e => setSelectedModelName(e.target.value)}
                  className="glass-input"
                  style={{
                    padding: "6px 12px",
                    fontSize: 12,
                    fontWeight: 600,
                    outline: "none",
                    border: "none",
                    color: "#fff",
                    cursor: "pointer"
                  }}
                >
                  {modelsData?.models?.map(m => (
                    <option key={m.name} value={m.name} style={{ background: "#1e293b" }}>
                      [AI] {m.name} {m.best ? " (Best Model)" : ""}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* Fare classes comparison grid */}
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "0 4px" }}>
                <span style={{ fontSize: 12, fontWeight: 700, textTransform: "uppercase", color: "var(--color-text-secondary)" }}>So sánh các hạng vé & Giá AI gợi ý</span>
                <button
                  onClick={handleApplyAllAiPrices}
                  disabled={aiLoading || fareFamilies.length === 0}
                  className="glass-button"
                  style={{
                    padding: "6px 14px",
                    borderRadius: 20,
                    border: "1px solid rgba(52, 211, 153, 0.25)",
                    background: "rgba(52, 211, 153, 0.12)",
                    color: "var(--color-text-success)",
                    fontSize: 11,
                    fontWeight: 700,
                    cursor: "pointer",
                    boxShadow: "0 4px 12px rgba(52, 211, 153, 0.1)"
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <IconSparkles />
                    <span>Áp dụng toàn bộ gợi ý AI</span>
                  </div>
                </button>
              </div>

              {famLoading ? (
                <div style={{ display: "flex", flex: 1, padding: 40, justifyContent: "center" }}><Spinner /></div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {fareFamilies.map(f => {
                    const uiClass = f.fare_family === "Business" ? "GDS" : f.fare_family;
                    const isFocused = f.id === focusedFamId;
                    const actualPrice = editedPrices[f.id] ?? f.price;
                    const actualLf = editedLfs[f.id] ?? f.lf;
                    const aiSuggestedPrice = getAiSuggestedPrice(f);
                    const isDiff = aiSuggestedPrice != null && actualPrice !== aiSuggestedPrice;
                    const diffPct = aiSuggestedPrice ? ((actualPrice - aiSuggestedPrice) / aiSuggestedPrice * 100) : 0;

                    return (
                      <div key={f.id}
                        onClick={() => setFocusedFamId(f.id)}
                        className="glass-panel"
                        style={{
                          borderRadius: 14,
                          padding: "14px 18px",
                          border: isFocused ? "1.5px solid var(--color-border-info)" : "1px solid rgba(255, 255, 255, 0.05)",
                          boxShadow: isFocused ? "0 8px 32px rgba(255, 79, 94, 0.12)" : "0 4px 12px rgba(0,0,0,0.15)",
                          cursor: "pointer",
                          display: "grid",
                          gridTemplateColumns: "1.2fr 1.5fr 1.2fr 1.2fr auto",
                          gap: 16,
                          alignItems: "center",
                          transition: "all 0.3s cubic-bezier(0.16, 1, 0.3, 1)"
                        }}>

                        {/* Class indicator badge */}
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <span style={{
                            width: 10, height: 10, borderRadius: "50%",
                            background: CLASS_COLORS[uiClass] || "#666"
                          }} />
                          <div>
                            <span style={{ fontSize: 13, fontWeight: 700, color: "var(--color-text-primary)" }}>{uiClass}</span>
                            <div style={{ fontSize: 9, color: "var(--color-text-secondary)", fontFamily: "var(--font-mono)", textTransform: "uppercase" }}>
                              Hạng: {f.str_Fare_Category || f.fare_category || "N/A"}
                            </div>
                          </div>
                        </div>

                        {/* Actual Price Edit box */}
                        <div style={{ display: "flex", flexDirection: "column", gap: 4 }} onClick={e => e.stopPropagation()}>
                          <span style={{ fontSize: 10, color: "var(--color-text-secondary)", fontWeight: 500 }}>Giá thực tế</span>
                          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                            <input
                              type="number"
                              value={Math.round(actualPrice)}
                              onChange={e => {
                                const val = parseFloat(e.target.value) || 0;
                                setEditedPrices(prev => ({ ...prev, [f.id]: val }));
                                if (f.id === focusedFamId) {
                                  handleSandboxChange(val, Math.round(actualLf * 100));
                                }
                              }}
                              className="glass-input"
                              style={{
                                width: "100%",
                                padding: "6px 10px",
                                border: "none",
                                color: "var(--color-text-primary)",
                                fontSize: 13,
                                fontWeight: 700,
                                fontFamily: "var(--font-mono)"
                              }}
                            />
                            <span style={{ fontSize: 11, color: "var(--color-text-secondary)", fontWeight: 600 }}>đ</span>
                          </div>
                        </div>

                        {/* Load factor status progress bar */}
                        <div style={{ display: "flex", flexDirection: "column", gap: 4 }} onClick={e => e.stopPropagation()}>
                          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--color-text-secondary)" }}>
                            <span>Tỉ lệ lấp đầy (LF)</span>
                            <span style={{ fontWeight: 700, color: "var(--color-text-primary)" }}>{Math.round(actualLf * 100)}%</span>
                          </div>
                          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                            <input
                              type="number"
                              min="0"
                              max="100"
                              value={Math.round(actualLf * 100)}
                              onChange={e => {
                                const val = (parseFloat(e.target.value) || 0) / 100;
                                setEditedLfs(prev => ({ ...prev, [f.id]: val }));
                                if (f.id === focusedFamId) {
                                  handleSandboxChange(actualPrice, Math.round(val * 100));
                                }
                              }}
                              className="glass-input"
                              style={{
                                width: 55,
                                padding: "6px 8px",
                                border: "none",
                                color: "var(--color-text-primary)",
                                fontSize: 12,
                                fontWeight: 700,
                                fontFamily: "var(--font-mono)",
                                textAlign: "center"
                              }}
                            />
                            <div style={{ flex: 1, height: 6, background: "rgba(255,255,255,0.08)", borderRadius: 3, overflow: "hidden" }}>
                              <div style={{
                                width: Math.round(actualLf * 100) + "%",
                                height: "100%",
                                background: CLASS_COLORS[uiClass] || "#666",
                                borderRadius: 3
                              }} />
                            </div>
                          </div>
                        </div>

                        {/* AI Prediction results display (strictly matching main suggestions) */}
                        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                          <span style={{ fontSize: 10, color: "var(--color-text-secondary)", fontWeight: 500 }}>Gợi ý từ AI</span>
                          <span style={{ fontSize: 13, fontWeight: 800, fontFamily: "var(--font-mono)", color: "var(--color-text-success)" }}>
                            {aiLoading ? (
                              <span style={{ fontSize: 11, fontWeight: 400, color: "var(--color-text-secondary)" }}>Đang tính...</span>
                            ) : aiSuggestedPrice != null ? (
                              `${fmt(aiSuggestedPrice)}đ`
                            ) : "--"}
                          </span>
                          {/* Chênh lệch phần trăm */}
                          {!aiLoading && aiSuggestedPrice != null && isDiff && (
                            <span style={{
                              fontSize: 10,
                              fontWeight: 700,
                              color: diffPct > 0 ? "var(--color-text-danger)" : "var(--color-text-success)"
                            }}>
                              {diffPct > 0 ? `+${diffPct.toFixed(1)}%` : `${diffPct.toFixed(1)}%`}
                            </span>
                          )}
                        </div>

                        {/* Apply single AI price button */}
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleApplyAiPrice(f);
                          }}
                          disabled={aiLoading || aiSuggestedPrice == null}
                          title="Áp dụng giá gợi ý AI này làm giá thực tế"
                          className="glass-button"
                          style={{
                            padding: "6px 10px",
                            borderRadius: 8,
                            border: "1px solid rgba(255, 79, 94, 0.2)",
                            background: "rgba(255, 79, 94, 0.1)",
                            color: "var(--color-text-info)",
                            fontSize: 11,
                            fontWeight: 700,
                            cursor: "pointer",
                            boxShadow: "0 2px 8px rgba(0,0,0,0.15)"
                          }}
                        >
                          Lấy giá AI
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Bottom Actions to save updates to Database */}
            <div 
              className="glass-panel"
              style={{
                marginTop: "auto",
                padding: "16px 20px",
                borderRadius: 14,
                boxShadow: "0 10px 30px rgba(0,0,0,0.15)",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center"
              }}
            >
              <span style={{ fontSize: 11, color: "var(--color-text-secondary)", fontWeight: 500 }}>
                * Thay đổi giá sẽ chỉ được cập nhật vĩnh viễn vào SQL Server khi nhấn lưu.
              </span>
              <div style={{ display: "flex", gap: 10 }}>
                <button
                  onClick={handleSaveChanges}
                  disabled={applyStatus === "saving" || fareFamilies.length === 0}
                  className="glass-button"
                  style={{
                    padding: "10px 24px",
                    borderRadius: 10,
                    border: applyStatus === "ok" ? "1px solid rgba(52, 211, 153, 0.25)"
                      : applyStatus === "error" ? "1px solid rgba(248, 113, 113, 0.25)"
                      : "none",
                    background: applyStatus === "ok" ? "rgba(52, 211, 153, 0.15)"
                      : applyStatus === "error" ? "rgba(248, 113, 113, 0.15)"
                      : "var(--color-text-info)",
                    color: applyStatus === "ok" ? "var(--color-text-success)"
                      : applyStatus === "error" ? "var(--color-text-danger)"
                      : "#fff",
                    fontSize: 12,
                    fontWeight: 700,
                    cursor: (applyStatus === "saving" || fareFamilies.length === 0) ? "not-allowed" : "pointer",
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    boxShadow: !applyStatus ? "0 4px 15px rgba(255, 79, 94, 0.25)" : "none"
                  }}
                >
                  {applyStatus === "saving" && <><span style={{ width: 12, height: 12, border: "2px solid #fff", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.8s linear infinite" }} /> Đang lưu...</>}
                  {applyStatus === "ok" && <><IconCheck /> Đã lưu thành công!</>}
                  {applyStatus === "error" && <><IconWarning /> Lỗi xảy ra! Thử lại</>}
                  {!applyStatus && <><IconCheck /> Lưu cấu hình giá & LF</>}
                </button>
              </div>
            </div>

          </div>

          {/* RIGHT: Focused class What-If sandbox & elasticity optimization */}
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {focusedFam ? (
              <div 
                className="glass-panel"
                style={{
                  borderRadius: 16,
                  padding: "20px",
                  boxShadow: "0 10px 30px rgba(0,0,0,0.15)",
                  display: "flex",
                  flexDirection: "column",
                  gap: 16,
                  height: "100%"
                }}
              >
                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, marginBottom: 4 }}>
                    <span style={{
                      width: 8, height: 8, borderRadius: "50%",
                      background: CLASS_COLORS[focusedFam.fare_family === "Business" ? "GDS" : focusedFam.fare_family]
                    }} />
                    <h4 style={{ margin: 0, fontSize: 14, fontWeight: 700, color: "var(--color-text-primary)" }}>
                      Hạng vé đang tối ưu: {focusedFam.fare_family === "Business" ? "GDS" : focusedFam.fare_family}
                    </h4>
                  </div>
                  <p style={{ margin: 0, fontSize: 11, color: "var(--color-text-secondary)" }}>
                    Kéo thanh trượt bên dưới để giả định sự thay đổi và tính toán doanh thu mục tiêu.
                  </p>
                </div>

                {/* Sandbox Sliders */}
                <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                  {/* Load Factor Slider */}
                  <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
                      <span style={{ color: "var(--color-text-secondary)", fontWeight: 500 }}>Load Factor (Tỉ lệ lấp đầy):</span>
                      <span style={{ fontWeight: 700, fontFamily: "var(--font-mono)", color: "var(--color-text-primary)" }}>{activeFocusedLf}%</span>
                    </div>
                    <input
                      type="range"
                      min="10"
                      max="100"
                      value={activeFocusedLf}
                      onChange={e => handleSandboxChange(activeFocusedPrice, parseInt(e.target.value))}
                      style={{ height: 6, margin: "8px 0" }}
                    />
                  </div>

                  {/* Price Slider */}
                  <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
                      <span style={{ color: "var(--color-text-secondary)", fontWeight: 500 }}>Giá vé (VND):</span>
                      <span style={{ fontWeight: 700, fontFamily: "var(--font-mono)", color: "var(--color-text-primary)" }}>{fmt(activeFocusedPrice)}đ</span>
                    </div>
                    <input
                      type="range"
                      min="100000"
                      max="30000000"
                      step="50000"
                      value={activeFocusedPrice}
                      onChange={e => handleSandboxChange(parseFloat(e.target.value), activeFocusedLf)}
                      style={{ height: 6, margin: "8px 0" }}
                    />
                  </div>
                </div>

                {/* Scipy Optimization Results */}
                {optResult && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                      <div 
                        className="glass-panel"
                        style={{ borderRadius: 10, padding: "12px 14px", background: "rgba(255,255,255,0.03)", border: "none" }}
                      >
                        <div style={{ fontSize: 9, color: "var(--color-text-secondary)", textTransform: "uppercase", fontWeight: 700 }}>Tăng trưởng doanh thu</div>
                        <div style={{ fontSize: 20, fontWeight: 800, fontFamily: "var(--font-mono)", color: optResult.revenue_delta_pct >= 0 ? "var(--color-text-success)" : "var(--color-text-danger)", marginTop: 2 }}>
                          {optResult.revenue_delta_pct >= 0 ? `+${optResult.revenue_delta_pct}%` : `${optResult.revenue_delta_pct}%`}
                        </div>
                      </div>
                      <div 
                        className="glass-panel"
                        style={{ borderRadius: 10, padding: "12px 14px", background: "rgba(255,255,255,0.03)", border: "none" }}
                      >
                        <div style={{ fontSize: 9, color: "var(--color-text-secondary)", textTransform: "uppercase", fontWeight: 700 }}>Giá tối ưu (Elasticity)</div>
                        <div style={{ fontSize: 18, fontWeight: 800, fontFamily: "var(--font-mono)", color: optColor, marginTop: 4 }}>
                          {fmt(optResult.optimal_price)}đ
                        </div>
                      </div>
                    </div>

                    {/* AI Explanation / recommendation */}
                    {optResult.recommendation && (
                      <div 
                        className="glass-panel"
                        style={{
                          borderLeft: "4px solid var(--color-border-info)",
                          padding: "10px 14px",
                          background: "var(--color-background-info)",
                          borderRadius: "0 10px 10px 0",
                          fontSize: 11,
                          lineHeight: 1.5,
                          color: "var(--color-text-secondary)",
                          border: "none",
                          borderLeftStyle: "solid",
                          borderLeftWidth: "4px",
                          borderLeftColor: "var(--color-border-info)"
                        }}
                      >
                        <strong style={{ color: "var(--color-text-primary)" }}>Khuyến nghị tối ưu:</strong> {optResult.recommendation}
                      </div>
                    )}
                  </div>
                )}

                {/* Simulation Revenue Curve AreaChart */}
                <div style={{ flex: 1, minHeight: 180, display: "flex", flexDirection: "column" }}>
                  <div style={{ fontSize: 10, fontWeight: 700, color: "var(--color-text-secondary)", textTransform: "uppercase", marginBottom: 6 }}>
                    Đồ thị doanh thu dựa trên độ co giãn cầu
                  </div>
                  <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
                    {simChartLoading ? (
                      <Spinner />
                    ) : simData.length > 0 ? (
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={simData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                          <defs>
                            <linearGradient id="colorRevenue" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%" stopColor="var(--color-text-info)" stopOpacity={0.3}/>
                              <stop offset="95%" stopColor="var(--color-text-info)" stopOpacity={0}/>
                            </linearGradient>
                          </defs>
                          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                          <XAxis dataKey="price_change_pct" tickFormatter={v => v + "%"} tick={{ fontSize: 9, fill: "var(--color-text-secondary)" }} />
                          <YAxis tickFormatter={v => (v / 1e6).toFixed(1) + "M"} tick={{ fontSize: 9, fill: "var(--color-text-secondary)" }} />
                          <Tooltip formatter={(value, name) => {
                            if (name === "new_revenue") return [fmt(value) + "đ", "Doanh thu giả lập"];
                            if (name === "new_price") return [fmt(value) + "đ", "Giá vé"];
                            return [value, name];
                          }} contentStyle={{ background: "rgba(15, 23, 42, 0.95)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 12, fontSize: 10, color: "#fff" }} />
                          <Area type="monotone" dataKey="new_revenue" stroke="var(--color-text-info)" strokeWidth={2} fillOpacity={1} fill="url(#colorRevenue)" />
                        </AreaChart>
                      </ResponsiveContainer>
                    ) : (
                      <span style={{ fontSize: 11, color: "var(--color-text-secondary)" }}>Không có dữ liệu đồ thị mô phỏng</span>
                    )}
                  </div>
                </div>

                {/* Competitor Price Comparison Section */}
                <div style={{
                  borderTop: "1px solid rgba(255, 255, 255, 0.08)",
                  paddingTop: "16px",
                  display: "flex",
                  flexDirection: "column",
                  gap: 12
                }}>
                  <div style={{ fontSize: 10, fontWeight: 700, color: "var(--color-text-secondary)", textTransform: "uppercase", display: "flex", alignItems: "center", gap: 6 }}>
                    <svg style={{ width: 12, height: 12, color: "var(--color-text-secondary)" }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <line x1="18" y1="20" x2="18" y2="10" />
                      <line x1="12" y1="20" x2="12" y2="4" />
                      <line x1="6" y1="20" x2="6" y2="14" />
                    </svg>
                    Đối chiếu giá vé đối thủ cạnh tranh (Vietjet vs. Competitors)
                  </div>
                  
                  {compLoading ? (
                    <div style={{ display: "flex", padding: 12, justifyContent: "center" }}><Spinner /></div>
                  ) : competitorPrices.length > 0 ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                      {/* Price BarChart */}
                      <div style={{ height: 160, width: "100%" }}>
                        <ResponsiveContainer width="100%" height="100%">
                          <BarChart data={[
                            { name: "VJ Hiện tại", Price: activeFocusedPrice, fill: "var(--color-text-danger, #d32f2f)" },
                            { name: "VJ AI gợi ý", Price: getAiSuggestedPrice(focusedFam) || activeFocusedPrice, fill: "var(--color-brand-yellow, #f57c00)" },
                            ...competitorPrices.map(c => ({
                              name: c.competitor.length > 15 ? c.competitor.substring(0, 12) + "..." : c.competitor,
                              Price: c.price,
                              fill: c.competitor.toLowerCase().includes("vietnam") ? "#856404" : "#0b6623"
                            }))
                          ]} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                            <XAxis dataKey="name" tick={{ fontSize: 9, fill: "var(--color-text-secondary)" }} />
                            <YAxis tickFormatter={v => (v / 1e3).toFixed(0) + "K"} tick={{ fontSize: 9, fill: "var(--color-text-secondary)" }} />
                            <Tooltip formatter={v => [fmt(v) + "đ", "Giá vé"]} contentStyle={{ background: "rgba(15, 23, 42, 0.95)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 12, fontSize: 10, color: "#fff" }} />
                            <Bar dataKey="Price" radius={[4, 4, 0, 0]}>
                              {
                                [
                                  { fill: "var(--color-text-danger, #d32f2f)" },
                                  { fill: "var(--color-brand-yellow, #f57c00)" },
                                  ...competitorPrices.map(c => ({
                                    fill: c.competitor.toLowerCase().includes("vietnam") ? "#856404" : "#0b6623"
                                  }))
                                ].map((entry, index) => (
                                  <Cell key={`cell-${index}`} fill={entry.fill} />
                                ))
                              }
                            </Bar>
                          </BarChart>
                        </ResponsiveContainer>
                      </div>

                      {/* Side-by-side prices details list */}
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                        {competitorPrices.map((c, idx) => {
                          const vjAiPrice = getAiSuggestedPrice(focusedFam) || activeFocusedPrice;
                          const gapVal = vjAiPrice - c.price;
                          const gapPct = c.price > 0 ? (gapVal / c.price * 100).toFixed(1) : "0.0";
                          return (
                            <div 
                              key={idx} 
                              className="glass-panel"
                              style={{
                                borderRadius: 10,
                                padding: "10px 12px",
                                fontSize: 11,
                                background: "rgba(255, 255, 255, 0.03)",
                                border: "none"
                              }}
                            >
                              <div style={{ fontWeight: 700, color: "var(--color-text-primary)", display: "flex", alignItems: "center", gap: 6 }}>
                                <span style={{ width: 6, height: 6, borderRadius: "50%", background: c.competitor.toLowerCase().includes("vietnam") ? "#856404" : "#0b6623" }} />
                                {c.competitor}
                              </div>
                              <div style={{ fontFamily: "var(--font-mono)", fontSize: 13, fontWeight: 700, marginTop: 4, color: "var(--color-text-secondary)" }}>
                                {fmt(c.price)}đ
                              </div>
                              <div style={{ fontSize: 9, color: gapVal > 0 ? "var(--color-text-danger)" : "var(--color-text-success)", fontWeight: 600, marginTop: 2 }}>
                                {gapVal > 0 ? `Đắt hơn (+${gapPct}%)` : `Rẻ hơn (${gapPct}%)`}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ) : (
                    <span style={{ fontSize: 11, color: "var(--color-text-secondary)" }}>Không tìm thấy dữ liệu giá đối thủ chặng này.</span>
                  )}
                </div>

              </div>
            ) : (
              <div 
                className="glass-panel"
                style={{
                  borderRadius: 16,
                  padding: "20px",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  textAlign: "center",
                  height: "100%",
                  color: "var(--color-text-secondary)",
                  fontSize: 12,
                  boxShadow: "0 10px 30px rgba(0,0,0,0.15)"
                }}
              >
                Vui lòng click chọn một hạng vé ở bảng bên trái để chạy công cụ mô phỏng What-If sandbox.
              </div>
            )}
          </div>

        </div>
      ) : (
        <div 
          className="glass-panel"
          style={{
            borderRadius: 16,
            padding: 40,
            textAlign: "center",
            color: "var(--color-text-secondary)",
            flex: 1,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: 12,
            boxShadow: "0 10px 30px rgba(0,0,0,0.15)"
          }}
        >
          <IconPlane size={42} style={{ color: "var(--color-text-info)", transform: "rotate(45deg)", marginBottom: 4 }} />
          <div style={{ fontSize: 14, fontWeight: 700, color: "var(--color-text-primary)" }}>Chưa chọn chuyến bay tối ưu</div>
          <p style={{ fontSize: 12, maxWidth: 400, margin: 0 }}>
            Vui lòng bấm chọn một chuyến bay từ danh sách tìm thấy ở trên (hoặc từ trang Danh sách chuyến bay) để xem và tối ưu giá chi tiết cho từng hạng vé.
          </p>
        </div>
      )}

    </div>
  );
}
