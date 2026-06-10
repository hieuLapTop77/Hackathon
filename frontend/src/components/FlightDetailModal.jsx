import { useState, useEffect, useRef } from "react";
import { Spinner } from "./Spinner";
import { IconCheck, IconBot, IconStar, IconWarning, IconClose, IconEllipsisVertical } from "./icons";
import { fmt, fmtPct, getLFColor } from "../utils/formatters";
import { API_BASE_URL as API } from "../config";

const FARE_FAMILY_COLORS = {
  "Eco": "#4CAF50",
  "Eco-Premium": "#2196F3",
  "SkyBoss": "#9C27B0",
  "Business": "#FF9800",
};


function validatePrice(price) {
  const num = parseFloat(price);
  if (isNaN(num) || num <= 0) return "Price must be > 0";
  if (num > 100_000_000) return "Price must be < 100M";
  return null;
}

export function FlightDetailModal({ flight, onClose, onSave }) {
  const [detail, setDetail]         = useState(null);
  const [loading, setLoading]       = useState(true);
  const [editedPrices, setEditedPrices] = useState({});
  const [editedLfs, setEditedLfs]       = useState({});
  const [saving, setSaving]         = useState(false);
  const [dragItem, setDragItem]     = useState(null);
  const [dragOverItem, setDragOverItem] = useState(null);
  const [fareFamilies, setFareFamilies] = useState([]);
  const [priceErrors, setPriceErrors] = useState({});
  const pricesRef = useRef({});
  const lfsRef = useRef({});

  // ── AI Simulator State ──────────────────────────────────────────────────────
  const [models, setModels] = useState([]);
  const [selectedModel, setSelectedModel] = useState("");
  const [selectedFamId, setSelectedFamId] = useState(null);

  const [simLeadTime, setSimLeadTime] = useState(30);
  const [simLf, setSimLf] = useState(0.5);
  const [simLfFare, setSimLfFare] = useState(0.4);
  const [simVelocity3d, setSimVelocity3d] = useState(0.02);
  const [simVelocity7d, setSimVelocity7d] = useState(0.05);
  const [simWeekday, setSimWeekday] = useState(4);
  const [simIsHoliday, setSimIsHoliday] = useState(0);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const [simPrice, setSimPrice] = useState(null);
  const [simClamped, setSimClamped] = useState(false);
  const [simLoading, setSimLoading] = useState(false);
  const [simError, setSimError] = useState(null);

  // Load models on mount
  useEffect(() => {
    fetch(`${API}/models`)
      .then(r => r.json())
      .then(data => {
        setModels(data.models || []);
        setSelectedModel(data.best_model || "XGBoost");
      })
      .catch(e => console.error("Error fetching models:", e));
  }, []);

  // Fetch flight details and other families for the same flight route concurrently
  useEffect(() => {
    if (!flight?.id || !flight?.flight_date) return;
    
    setLoading(true);
    setPriceErrors({});
    
    let isMounted = true;
    
    const fetchFlightAndFamilies = async () => {
      try {
        const [detailRes, familiesRes] = await Promise.all([
          fetch(`${API}/flights/${flight.id}`),
          fetch(`${API}/flights?date_from=${flight.flight_date}&date_to=${flight.flight_date}&limit=50`)
        ]);
        
        if (!detailRes.ok) throw new Error(`Detail fetch failed with status: ${detailRes.status}`);
        if (!familiesRes.ok) throw new Error(`Families fetch failed with status: ${familiesRes.status}`);
        
        const detailData = await detailRes.json();
        const familiesData = await familiesRes.json();
        
        if (!isMounted) return;
        
        const families = familiesData.filter(f => f.route === flight.route);
        
        const prices = {};
        const lfs = {};
        
        // Load default prices and lfs from fare families
        families.forEach(f => {
          prices[f.id] = f.price;
          lfs[f.id] = f.lf;
        });
        
        // Ensure the current flight is populated properly
        if (detailData.price) prices[detailData.id] = detailData.price;
        if (detailData.lf) lfs[detailData.id] = detailData.lf;
        
        setDetail(detailData);
        setFareFamilies(families);
        setEditedPrices(prices);
        setEditedLfs(lfs);
        pricesRef.current = { ...prices };
        lfsRef.current = { ...lfs };
        
        const match = families.find(x => x.id === flight.id) || families[0];
        if (match) {
          setSelectedFamId(match.id);
        } else {
          setSelectedFamId(detailData.id);
        }
      } catch (err) {
        if (isMounted) {
          console.error("Error fetching flight details and fare families:", err);
        }
      } finally {
        if (isMounted) {
          setLoading(false);
        }
      }
    };
    
    fetchFlightAndFamilies();
    
    return () => {
      isMounted = false;
    };
  }, [flight?.id, flight?.flight_date, flight?.route]);

  // Reset simulator values when selected fare family changes
  const selectedFam = fareFamilies.find(f => f.id === selectedFamId) || flight;
  useEffect(() => {
    if (!selectedFam) return;
    setSimLeadTime(selectedFam.lead_time_days ?? 30);
    setSimLf(selectedFam.lf ?? 0.65);
    setSimLfFare(selectedFam.LF_by_fare ?? selectedFam.lf ?? 0.40);
    setSimVelocity3d(selectedFam.booking_velocity_3d ?? 0.02);
    setSimVelocity7d(selectedFam.booking_velocity_7d ?? 0.05);
    setSimWeekday(selectedFam.Weekday ?? 4);
    setSimIsHoliday(selectedFam.IsHoliday ?? 0);
  }, [selectedFamId]);

  // Debounced real-time simulation API calls
  useEffect(() => {
    if (!selectedFam || !selectedModel) return;

    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setSimLoading(true);
      setSimError(null);
      try {
        const payload = {
          lead_time_days: parseInt(simLeadTime),
          LF_by_date: parseFloat(simLf),
          LF_by_fare: parseFloat(simLfFare),
          booking_velocity_3d: parseFloat(simVelocity3d),
          booking_velocity_7d: parseFloat(simVelocity7d),
          Weekday: parseInt(simWeekday),
          IsHoliday: parseInt(simIsHoliday),
          is_oneway: selectedFam.is_oneway ?? 1,
          lng_fuel: selectedFam.lng_fuel ?? 93.86,
          capacity: selectedFam.lng_Capacity ?? selectedFam.capacity ?? 230,
          count_sked: selectedFam.count_sked ?? 3,
          fare_family: selectedFam.fare_family || "Eco",
          fare_category: selectedFam.str_Fare_Category || selectedFam.fare_category || "B",
          dep: selectedFam.str_Dep || selectedFam.dep || "SGN",
          arr: selectedFam.str_Arr || selectedFam.arr || "HAN",
          model_name: selectedModel,
        };

        const res = await fetch(`${API}/predict`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          signal: controller.signal,
        });

        if (!res.ok) throw new Error(`API error ${res.status}`);
        const data = await res.json();
        setSimPrice(data.predicted_price_vnd);
        setSimClamped(data.clamped || false);
      } catch (err) {
        if (err.name !== "AbortError") {
          setSimError("Lỗi kết nối dự đoán");
          console.error("Simulation error:", err);
        }
      } finally {
        setSimLoading(false);
      }
    }, 300); // 300ms debounce

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [
    selectedFamId,
    selectedFam,
    selectedModel,
    simLeadTime,
    simLf,
    simLfFare,
    simVelocity3d,
    simVelocity7d,
    simWeekday,
    simIsHoliday,
  ]);

  const handlePriceChange = (id, value) => {
    const newPrices = { ...editedPrices, [id]: value };
    setEditedPrices(newPrices);
    pricesRef.current = newPrices;
    setPriceErrors(prev => ({ ...prev, [id]: validatePrice(value) }));
  };

  const handleLfChange = (id, value) => {
    const newLfs = { ...editedLfs, [id]: value };
    setEditedLfs(newLfs);
    lfsRef.current = newLfs;

    // Validate load factor: must be between 0 and 1
    const num = parseFloat(value);
    let err = null;
    if (isNaN(num) || num < 0 || num > 1) {
      err = "LF must be 0% - 100%";
    }
    setPriceErrors(prev => ({ ...prev, [id + "_lf"]: err }));
  };

  const handleApplySimPrice = () => {
    if (simPrice == null || !selectedFamId) return;
    handlePriceChange(selectedFamId, simPrice.toString());
  };

  const hasErrors = () => Object.values(priceErrors).some(e => e !== null);

  const handleSave = async () => {
    const errors = {};
    let hasAnyError = false;
    Object.entries(pricesRef.current).forEach(([id, price]) => {
      const err = validatePrice(price);
      if (err) { errors[id] = err; hasAnyError = true; }
    });
    Object.entries(lfsRef.current).forEach(([id, lf]) => {
      const num = parseFloat(lf);
      if (isNaN(num) || num < 0 || num > 1) {
        errors[id + "_lf"] = "LF must be 0% - 100%";
        hasAnyError = true;
      }
    });
    setPriceErrors(errors);
    if (hasAnyError) return;

    setSaving(true);
    const updates = Object.entries(pricesRef.current).map(([id, price]) => {
      const dbId = parseInt(id);
      const lfVal = lfsRef.current[dbId] !== undefined ? parseFloat(lfsRef.current[dbId]) : 0.65;
      return {
        id: dbId,
        price: parseFloat(price) || 0,
        lf: lfVal,
      };
    });
    try {
      const res = await fetch(`${API}/flights/${flight.id}/fares`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ updates }),
      });
      if (res.ok) {
        const result = await res.json();
        onSave && onSave(result);
        onClose();
      }
    } catch (e) {
      console.error(e);
    } finally {
      setSaving(false);
    }
  };

  // Drag handlers
  const handleDragStart = (e, idx) => { setDragItem(idx); e.dataTransfer.effectAllowed = "move"; };
  const handleDragOver  = (e, idx)  => { e.preventDefault(); setDragOverItem(idx); };
  const handleDrop     = (e, idx)  => {
    e.preventDefault();
    if (dragItem === null || dragItem === idx) return;
    const newFamilies = [...fareFamilies];
    const [moved] = newFamilies.splice(dragItem, 1);
    newFamilies.splice(idx, 0, moved);
    setFareFamilies(newFamilies);
    setDragItem(null);
    setDragOverItem(null);
  };
  const handleDragEnd = () => { setDragItem(null); setDragOverItem(null); };

  if (!flight) return null;

  return (
    <div style={{
      position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
      background: "rgba(0,0,0,0.6)", display: "flex", alignItems: "center", justifyContent: "center",
      zIndex: 1000,
    }} onClick={onClose}>
      <div style={{
        background: "var(--color-background-primary)",
        borderRadius: "var(--border-radius-lg)",
        width: "95%", maxWidth: 980,
        maxHeight: "90vh",
        overflow: "hidden",
        display: "flex", flexDirection: "column",
      }} onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div style={{ padding: "16px 20px", borderBottom: "0.5px solid var(--color-border-tertiary)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 600 }}>
              {flight.route || flight.flight_no} - {flight.flight_date}
            </div>
            <div style={{ fontSize: 11, color: "var(--color-text-secondary)", marginTop: 2 }}>
              Flight details VJ | Select a row to run AI Simulation sandbox
            </div>
          </div>
          <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", padding: 4, color: "var(--color-text-secondary)" }}>
            <IconClose size={18} />
          </button>
        </div>

        {/* Content */}
        <div style={{ flex: 1, overflow: "auto", padding: "16px 20px" }}>
          {loading ? (
            <Spinner />
          ) : (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 24, alignItems: "stretch" }}>
              
              {/* Left Column: Summary + Fare families */}
              <div style={{ flex: "1 1 450px", minWidth: 320, display: "flex", flexDirection: "column", gap: 16 }}>
                
                {/* Summary */}
                {detail && (
                  <div style={{ display: "flex", gap: 12 }}>
                    {[
                      { label: "Load Factor", value: `${Math.round(detail.lf * 100)}%`, color: getLFColor(detail.lf) },
                      { label: "Gia toi uu",   value: `${fmt(detail.optimal_price)} VND`, color: "var(--color-text-success)" },
                      { label: "Thay doi",     value: fmtPct(detail.price_change_pct), color: detail.price_change_pct > 0 ? "var(--color-text-danger)" : detail.price_change_pct < 0 ? "var(--color-text-success)" : "var(--color-text-info)" },
                    ].map(({ label, value, color }) => (
                      <div key={label} style={{ background: "var(--color-background-secondary)", borderRadius: 8, padding: "10px 14px", flex: 1 }}>
                        <div style={{ fontSize: 10, color: "var(--color-text-secondary)", textTransform: "uppercase" }}>{label}</div>
                        <div style={{ fontSize: 18, fontWeight: 600, fontFamily: "var(--font-mono)", color }}>
                          {value}
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {/* Fare families */}
                <div>
                  <div style={{ fontSize: 11, fontWeight: 500, marginBottom: 8, color: "var(--color-text-secondary)" }}>
                    DANH SÁCH HẠNG VÉ ({fareFamilies.length} hạng)
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {fareFamilies.map((f, idx) => {
                      const isSelected = f.id === selectedFamId;
                      return (
                        <div key={f.id}
                          draggable
                          onDragStart={e => handleDragStart(e, idx)}
                          onDragOver={e => handleDragOver(e, idx)}
                          onDrop={e => handleDrop(e, idx)}
                          onDragEnd={handleDragEnd}
                          onClick={() => setSelectedFamId(f.id)}
                          style={{
                            background: isSelected ? "var(--color-background-info)" : dragOverItem === idx ? "var(--color-background-info)" : "var(--color-background-secondary)",
                            borderRadius: 8,
                            padding: "12px 14px",
                            display: "flex",
                            alignItems: "center",
                            gap: 12,
                            border: isSelected ? "1.5px solid var(--color-border-info)" : "1px solid var(--color-border-tertiary)",
                            borderColor: isSelected ? "var(--color-border-info)" : dragItem === idx ? "var(--color-border-info)" : dragOverItem === idx ? "var(--color-border-success)" : "var(--color-border-tertiary)",
                            cursor: "pointer",
                            opacity: dragItem === idx ? 0.5 : 1,
                            transition: "all .15s",
                          }}>
                          <div style={{ color: "var(--color-text-secondary)", display: "flex", alignItems: "center", cursor: "grab" }} onClick={e => e.stopPropagation()}>
                            <IconEllipsisVertical size={16} />
                          </div>
                          
                          <div style={{
                            padding: "4px 10px", borderRadius: 20, fontSize: 10, fontWeight: 600,
                            background: FARE_FAMILY_COLORS[f.fare_family] || "#666", color: "#fff", minWidth: 90, textAlign: "center",
                            display: "flex", flexDirection: "column", alignItems: "center"
                          }}>
                            {f.fare_family || "N/A"}
                            {isSelected && (
                              <span style={{ fontSize: 7, textTransform: "uppercase", letterSpacing: 0.5, marginTop: 1, color: "rgba(255,255,255,0.8)" }}>Mô phỏng</span>
                            )}
                          </div>

                          <div style={{ flex: 1 }}>
                            <div style={{ fontSize: 10, color: "var(--color-text-secondary)", marginBottom: 3 }}>
                              LF {Math.round((editedLfs[f.id] !== undefined ? editedLfs[f.id] : f.lf) * 100)}%
                            </div>
                            <div style={{ height: 4, background: "var(--color-border-tertiary)", borderRadius: 2, overflow: "hidden" }}>
                              <div style={{
                                width: Math.round((editedLfs[f.id] !== undefined ? editedLfs[f.id] : f.lf) * 100) + "%",
                                height: "100%",
                                background: getLFColor(editedLfs[f.id] !== undefined ? editedLfs[f.id] : f.lf),
                                borderRadius: 2
                              }} />
                            </div>
                          </div>

                          <div style={{ fontSize: 10, color: "var(--color-text-secondary)", minWidth: 80, textAlign: "right" }}>
                            Current Price
                            <div style={{ fontSize: 13, fontWeight: 600, fontFamily: "var(--font-mono)", color: "var(--color-text-secondary)" }}>{fmt(f.price)}</div>
                          </div>

                          <div style={{ display: "flex", flexDirection: "column", gap: 2 }} onClick={e => e.stopPropagation()}>
                            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                              {/* Price Input */}
                              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                                <input
                                  type="number"
                                  placeholder="Giá vé"
                                  value={editedPrices[f.id] !== undefined ? editedPrices[f.id] : f.price}
                                  onChange={e => handlePriceChange(f.id, e.target.value)}
                                  style={{
                                    width: 90, padding: "5px 8px", borderRadius: 6,
                                    border: priceErrors[f.id] ? "0.5px solid var(--color-border-danger)" : "0.5px solid var(--color-border-info)",
                                    background: "var(--color-background-primary)", color: "var(--color-text-primary)",
                                    fontSize: 11, fontFamily: "var(--font-mono)", fontWeight: 500,
                                  }}
                                />
                              </div>

                              {/* Load Factor Input */}
                              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                                <input
                                  type="number"
                                  min="0"
                                  max="100"
                                  placeholder="LF %"
                                  value={editedLfs[f.id] !== undefined ? Math.round(editedLfs[f.id] * 100) : Math.round(f.lf * 100)}
                                  onChange={e => handleLfChange(f.id, parseFloat(e.target.value) / 100)}
                                  style={{
                                    width: 60, padding: "5px 8px", borderRadius: 6,
                                    border: priceErrors[f.id + "_lf"] ? "0.5px solid var(--color-border-danger)" : "0.5px solid var(--color-border-info)",
                                    background: "var(--color-background-primary)", color: "var(--color-text-primary)",
                                    fontSize: 11, fontFamily: "var(--font-mono)", fontWeight: 500,
                                  }}
                                />
                              </div>
                            </div>
                            {priceErrors[f.id] && (
                              <div style={{ fontSize: 8, color: "var(--color-text-danger)" }}>{priceErrors[f.id]}</div>
                            )}
                            {priceErrors[f.id + "_lf"] && (
                              <div style={{ fontSize: 8, color: "var(--color-text-danger)" }}>{priceErrors[f.id + "_lf"]}</div>
                            )}
                          </div>

                          <div style={{
                            minWidth: 50, fontSize: 11, fontWeight: 600, fontFamily: "var(--font-mono)", textAlign: "right",
                            color: (editedPrices[f.id] || f.price) > f.price ? "var(--color-text-danger)"
                                 : (editedPrices[f.id] || f.price) < f.price ? "var(--color-text-success)"
                                 : "var(--color-text-secondary)",
                          }}>
                            {((editedPrices[f.id] || f.price) - f.price) >= 0 ? "+" : ""}
                            {fmt((editedPrices[f.id] || f.price) - f.price)}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {fareFamilies.length === 0 && !loading && (
                  <div style={{ textAlign: "center", padding: 24, color: "var(--color-text-secondary)" }}>
                    No fare information found
                  </div>
                )}
              </div>

              {/* Right Column: AI What-If Simulator */}
              <div style={{
                flex: "1 1 350px", minWidth: 320,
                background: "var(--color-background-secondary)",
                borderRadius: 12,
                padding: "16px 18px",
                border: "1px solid var(--color-border-tertiary)",
                display: "flex",
                flexDirection: "column",
                gap: 14,
                justifyContent: "space-between"
              }}>
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                    <span style={{ color: "var(--color-text-info)", display: "flex" }}><IconBot /></span>
                    <h4 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>Bộ giả lập định giá AI (What-If)</h4>
                  </div>
                  <p style={{ margin: "0 0 12px 0", fontSize: 11, color: "var(--color-text-secondary)" }}>
                    Kéo thanh trượt để thay đổi thông số và quan sát giá vé đề xuất thay đổi tương ứng.
                  </p>

                  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    
                    {/* Model selector */}
                    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                      <label style={{ fontSize: 10, fontWeight: 600, color: "var(--color-text-secondary)", textTransform: "uppercase" }}>Chọn Model AI</label>
                      <select
                        value={selectedModel}
                        onChange={e => setSelectedModel(e.target.value)}
                        style={{
                          padding: "6px 10px", borderRadius: 6,
                          border: "0.5px solid var(--color-border-tertiary)",
                          background: "var(--color-background-primary)", color: "var(--color-text-primary)",
                          fontSize: 12
                        }}
                      >
                        {models.map(m => (
                          <option key={m.name} value={m.name}>
                            {m.name} {m.best ? " (Best Model)" : ""}
                          </option>
                        ))}
                      </select>
                    </div>

                    {/* Target fare details */}
                    <div style={{ background: "var(--color-background-primary)", padding: "8px 10px", borderRadius: 6, border: "0.5px solid var(--color-border-tertiary)", fontSize: 11 }}>
                      <div style={{ display: "flex", justifyContent: "space-between" }}>
                        <span style={{ color: "var(--color-text-secondary)" }}>Đang mô phỏng hạng:</span>
                        <span style={{ fontWeight: 600, color: "var(--color-text-primary)" }}>{selectedFam?.fare_family} ({selectedFam?.str_Fare_Category || selectedFam?.fare_category})</span>
                      </div>
                    </div>

                    {/* Lead Time Slider */}
                    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
                        <span style={{ color: "var(--color-text-secondary)" }}>Lead Time (Ngày còn lại):</span>
                        <span style={{ fontWeight: 600, fontFamily: "var(--font-mono)" }}>{simLeadTime} ngày</span>
                      </div>
                      <input
                        type="range"
                        min="1"
                        max="90"
                        value={simLeadTime}
                        onChange={e => setSimLeadTime(parseInt(e.target.value))}
                        style={{ width: "100%" }}
                      />
                    </div>

                    {/* LF Slider */}
                    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
                        <span style={{ color: "var(--color-text-secondary)" }}>Load Factor (Tỉ lệ lấp đầy):</span>
                        <span style={{ fontWeight: 600, fontFamily: "var(--font-mono)" }}>{Math.round(simLf * 100)}%</span>
                      </div>
                      <input
                        type="range"
                        min="0"
                        max="1"
                        step="0.01"
                        value={simLf}
                        onChange={e => setSimLf(parseFloat(e.target.value))}
                        style={{ width: "100%" }}
                      />
                    </div>

                    {/* Advanced Controls Toggle */}
                    <button
                      onClick={() => setShowAdvanced(!showAdvanced)}
                      style={{
                        background: "none", border: "none", color: "var(--color-text-info)",
                        fontSize: 11, cursor: "pointer", display: "flex", alignItems: "center",
                        gap: 4, padding: "4px 0", alignSelf: "flex-start"
                      }}
                    >
                      {showAdvanced ? "▼ Ẩn cấu hình nâng cao" : "▶ Hiện cấu hình nâng cao"}
                    </button>

                    {showAdvanced && (
                      <div style={{ display: "flex", flexDirection: "column", gap: 8, padding: "8px", background: "var(--color-background-primary)", borderRadius: 6, border: "0.5px solid var(--color-border-tertiary)" }}>
                        
                        {/* LF by Fare Slider */}
                        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10 }}>
                            <span style={{ color: "var(--color-text-secondary)" }}>LF theo hạng vé:</span>
                            <span style={{ fontWeight: 600, fontFamily: "var(--font-mono)" }}>{Math.round(simLfFare * 100)}%</span>
                          </div>
                          <input
                            type="range"
                            min="0"
                            max="1"
                            step="0.01"
                            value={simLfFare}
                            onChange={e => setSimLfFare(parseFloat(e.target.value))}
                            style={{ width: "100%" }}
                          />
                        </div>

                        {/* Booking velocity 3d */}
                        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10 }}>
                            <span style={{ color: "var(--color-text-secondary)" }}>Booking Velocity 3D:</span>
                            <span style={{ fontWeight: 600, fontFamily: "var(--font-mono)" }}>{(simVelocity3d * 100).toFixed(1)}%</span>
                          </div>
                          <input
                            type="range"
                            min="0"
                            max="0.2"
                            step="0.005"
                            value={simVelocity3d}
                            onChange={e => setSimVelocity3d(parseFloat(e.target.value))}
                            style={{ width: "100%" }}
                          />
                        </div>

                        {/* Booking velocity 7d */}
                        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10 }}>
                            <span style={{ color: "var(--color-text-secondary)" }}>Booking Velocity 7D:</span>
                            <span style={{ fontWeight: 600, fontFamily: "var(--font-mono)" }}>{(simVelocity7d * 100).toFixed(1)}%</span>
                          </div>
                          <input
                            type="range"
                            min="0"
                            max="0.4"
                            step="0.01"
                            value={simVelocity7d}
                            onChange={e => setSimVelocity7d(parseFloat(e.target.value))}
                            style={{ width: "100%" }}
                          />
                        </div>

                        {/* Weekday dropdown */}
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
                          <span style={{ fontSize: 10, color: "var(--color-text-secondary)" }}>Thứ trong tuần:</span>
                          <select
                            value={simWeekday}
                            onChange={e => setSimWeekday(parseInt(e.target.value))}
                            style={{
                              padding: "4px 8px", borderRadius: 4,
                              border: "0.5px solid var(--color-border-tertiary)",
                              background: "var(--color-background-secondary)", color: "var(--color-text-primary)",
                              fontSize: 10
                            }}
                          >
                            <option value="0">Thứ 2</option>
                            <option value="1">Thứ 3</option>
                            <option value="2">Thứ 4</option>
                            <option value="3">Thứ 5</option>
                            <option value="4">Thứ 6</option>
                            <option value="5">Thứ 7</option>
                            <option value="6">Chủ nhật</option>
                          </select>
                        </div>

                        {/* Holiday Toggle */}
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                          <span style={{ fontSize: 10, color: "var(--color-text-secondary)" }}>Ngày Lễ / Tết:</span>
                          <input
                            type="checkbox"
                            checked={simIsHoliday === 1}
                            onChange={e => setSimIsHoliday(e.target.checked ? 1 : 0)}
                            style={{ cursor: "pointer" }}
                          />
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                {/* Prediction results area */}
                <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 8 }}>
                  <div style={{
                    background: "var(--color-background-primary)",
                    borderRadius: 8,
                    padding: "14px 16px",
                    border: "0.5px solid var(--color-border-tertiary)",
                    textAlign: "center",
                    display: "flex",
                    flexDirection: "column",
                    justifyContent: "center",
                    minHeight: 85
                  }}>
                    {simLoading ? (
                      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
                        <span style={{ width: 14, height: 14, border: "2px solid var(--color-border-info)", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.8s linear infinite" }} />
                        <span style={{ fontSize: 11, color: "var(--color-text-secondary)" }}>Đang tính toán giá AI...</span>
                      </div>
                    ) : simError ? (
                      <span style={{ color: "var(--color-text-danger)", fontSize: 11 }}>{simError}</span>
                    ) : simPrice != null ? (
                      <div>
                        <div style={{ fontSize: 10, color: "var(--color-text-secondary)", textTransform: "uppercase", marginBottom: 2 }}>Giá đề xuất từ AI</div>
                        <div style={{ fontSize: 22, fontWeight: 700, color: "var(--color-text-success)", fontFamily: "var(--font-mono)", display: "flex", alignItems: "center", justifyContent: "center", gap: 4 }}>
                          {fmt(simPrice)} VND
                          {simClamped && (
                            <span title="Dự đoán gốc từ model nằm ngoài biên thực tế, đã tự động hiệu chỉnh tối ưu." style={{ color: "var(--color-text-warning)", display: "inline-flex", cursor: "help" }}><IconWarning /></span>
                          )}
                        </div>
                        {selectedFam && selectedFam.price > 0 && (
                          <div style={{
                            fontSize: 10,
                            marginTop: 4,
                            fontWeight: 500,
                            color: simPrice > selectedFam.price ? "var(--color-text-danger)"
                                 : simPrice < selectedFam.price ? "var(--color-text-success)"
                                 : "var(--color-text-secondary)"
                          }}>
                            {simPrice > selectedFam.price ? "+" : ""}
                            {(((simPrice - selectedFam.price) / selectedFam.price) * 100).toFixed(1)}% so với giá hiện tại ({fmt(selectedFam.price)})
                          </div>
                        )}
                      </div>
                    ) : (
                      <span style={{ color: "var(--color-text-secondary)", fontSize: 11 }}>Chọn model và nhập thông tin</span>
                    )}
                  </div>

                  <button
                    onClick={handleApplySimPrice}
                    disabled={simPrice == null || simLoading}
                    style={{
                      width: "100%",
                      padding: "9px 12px",
                      borderRadius: 6,
                      background: (simPrice == null || simLoading) ? "var(--color-background-secondary)" : "var(--color-background-success)",
                      color: (simPrice == null || simLoading) ? "var(--color-text-secondary)" : "var(--color-text-success)",
                      fontWeight: 600,
                      border: "none",
                      cursor: (simPrice == null || simLoading) ? "not-allowed" : "pointer",
                      fontSize: 12,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      gap: 6,
                      transition: "all 0.15s"
                    }}
                  >
                    <IconCheck /> Áp dụng giá AI này
                  </button>
                </div>

              </div>

            </div>
          )}
        </div>

        {/* Footer */}
        <div style={{ padding: "14px 20px", borderTop: "0.5px solid var(--color-border-tertiary)", display: "flex", justifyContent: "flex-end", gap: 10 }}>
          <button onClick={onClose} style={{
            padding: "8px 16px", borderRadius: 6, border: "0.5px solid var(--color-border-tertiary)",
            background: "transparent", color: "var(--color-text-secondary)", fontSize: 12, cursor: "pointer",
          }}>
            Close
          </button>
          <button onClick={handleSave} disabled={saving || hasErrors()} style={{
            padding: "8px 20px", borderRadius: 6, border: "none",
            background: saving ? "var(--color-background-secondary)" : hasErrors() ? "var(--color-background-secondary)" : "var(--color-background-success)",
            color: saving ? "var(--color-text-secondary)" : hasErrors() ? "var(--color-text-secondary)" : "var(--color-text-success)",
            fontSize: 12, fontWeight: 600, cursor: (saving || hasErrors()) ? "not-allowed" : "pointer",
            opacity: (saving || hasErrors()) ? 0.6 : 1,
          }}>
            {saving ? "Saving..." : hasErrors() ? "Please check prices" : "Save changes"}
          </button>
        </div>
      </div>
    </div>
  );
}
