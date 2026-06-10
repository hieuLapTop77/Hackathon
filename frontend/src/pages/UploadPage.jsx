import { useState, useRef } from "react";
import { IconRefresh, IconWarning, IconCheck, IconSearch, IconCalendar, IconFolder, IconInbox, IconFileText, IconDatabase, IconLightning } from "../components/icons";
import { fmt } from "../utils/formatters";

import { API_BASE_URL as API } from "../config";

function FileDropZone({ file, onFileChange, onReset }) {
  const fileRef = useRef();
  const [dragging, setDragging] = useState(false);

  const handleDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer?.files?.[0];
    if (f) onFileChange(f);
  };

  return (
    <div
      onDrop={handleDrop}
      onDragOver={e => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onClick={() => !file && fileRef.current?.click()}
      style={{
        border: `1.5px dashed ${dragging ? "var(--color-border-info)" : file ? "var(--color-border-success)" : "var(--color-border-info)"}`,
        borderRadius: 14,
        padding: "24px 20px",
        textAlign: "center",
        cursor: file ? "default" : "pointer",
        background: file ? "var(--color-background-success)" : "var(--color-background-secondary)",
        transition: "all .2s",
        minHeight: 180,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 10,
        boxShadow: "0 2px 4px rgba(0,0,0,0.01)"
      }}
    >
      <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls"
        style={{ display: "none" }} onChange={e => e.target.files?.[0] && onFileChange(e.target.files[0])} />
      {file ? (
        <>
          <span style={{ color: "var(--color-text-success)", display: "flex" }}><IconFileText /></span>
          <div style={{ fontSize: 13, fontWeight: 700, color: "var(--color-text-success)" }}>{file.name}</div>
          <div style={{ fontSize: 11, color: "var(--color-text-secondary)" }}>{(file.size / 1024).toFixed(1)} KB</div>
          <button onClick={e => { e.stopPropagation(); onReset(); }}
            style={{ marginTop: 4, padding: "4px 12px", borderRadius: 8, border: "0.5px solid var(--color-border-secondary)", background: "var(--color-background-primary)", color: "var(--color-text-secondary)", fontSize: 11, cursor: "pointer", fontWeight: 600 }}>
            Thay đổi file
          </button>
        </>
      ) : (
        <>
          <span style={{ color: "var(--color-text-info)", display: "flex" }}><IconInbox /></span>
          <div style={{ fontSize: 13, fontWeight: 700, color: "var(--color-text-primary)" }}>Kéo thả file vào đây</div>
          <div style={{ fontSize: 11, color: "var(--color-text-secondary)" }}>Hỗ trợ tệp CSV hoặc Excel (.csv, .xlsx, .xls)</div>
        </>
      )}
    </div>
  );
}

export function UploadPage({ onGoToOverview }) {
  const [file, setFile] = useState(null);

  // Db saving state
  const [saveLoading, setSaveLoading] = useState(false);
  const [saveResult, setSaveResult] = useState(null);
  const [saveError, setSaveError] = useState(null);

  // Database Seeding State
  const [seedLoading, setSeedLoading] = useState(false);
  const [seedResult, setSeedResult] = useState(null);
  const [seedError, setSeedError] = useState(null);

  const handleFileChange = (f) => {
    setFile(f);
    setSaveResult(null);
    setSaveError(null);
    setSeedResult(null);
  };

  const handleReset = () => {
    setFile(null);
    setSaveResult(null);
    setSaveError(null);
    setSeedResult(null);
  };

  // Upload and commit directly to Database
  const handleConfirmSave = async () => {
    if (!file) return;
    setSaveLoading(true);
    setSaveError(null);
    const fd = new FormData();
    fd.append("file", file);

    try {
      const res = await fetch(`${API}/flights/upload`, { method: "POST", body: fd });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setSaveResult(data);
    } catch (e) {
      setSaveError(e.message);
    } finally {
      setSaveLoading(false);
    }
  };

  // One-click database seeding dashboard
  const handleSeedDatabase = async () => {
    setSeedLoading(true);
    setSeedError(null);
    setSeedResult(null);
    try {
      const res = await fetch(`${API}/db/seed`, { method: "POST" });
      if (!res.ok) throw new Error("Seed request failed");
      const data = await res.json();
      setSeedResult(data);
    } catch (e) {
      setSeedError(e.message);
    } finally {
      setSeedLoading(false);
    }
  };

  return (
    <div style={{ flex: 1, overflow: "auto", padding: "20px 24px", display: "flex", flexDirection: "column", gap: 20, background: "transparent" }}>
      
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <h2 style={{ fontSize: 20, fontWeight: 700, color: "var(--color-text-primary)" }}>Nạp dữ liệu chuyến bay (Upload Data Console)</h2>
          <p style={{ fontSize: 12, color: "var(--color-text-secondary)", marginTop: 2 }}>
            Nạp tệp Excel/CSV chứa lịch trình bay lên hệ thống để chẩn đoán, giả lập What-If và tối ưu giá.
          </p>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "340px 1fr", gap: 20, flex: 1, minHeight: 0 }}>
        
        {/* LEFT: Actions Pane */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          
          {/* File Dropzone */}
          <FileDropZone file={file} onFileChange={handleFileChange} onReset={handleReset} />

          {/* Upload directly to Database button */}
          {file && !saveResult && (
            <button onClick={handleConfirmSave} disabled={saveLoading}
              style={{
                padding: "11px 0", borderRadius: 10, border: "none",
                background: saveLoading ? "var(--color-background-secondary)" : "var(--color-text-info)",
                color: "#fff",
                fontSize: 12, fontWeight: 700, cursor: saveLoading ? "not-allowed" : "pointer",
                opacity: saveLoading ? 0.6 : 1, display: "flex", alignItems: "center",
                justifyContent: "center", gap: 8, transition: "all .2s",
                boxShadow: "0 2px 4px rgba(0,0,0,0.05)"
              }}>
              {saveLoading
                ? <><span style={{ width: 12, height: 12, border: "2px solid #fff", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.8s linear infinite" }} /> Đang tải lên...</>
                : <><IconDatabase /> Tải lên & Lưu vào Database</>}
            </button>
          )}

          {/* Quick seed database option */}
          {!file && !saveResult && !saveLoading && (
            <div className="glass-panel" style={{
              borderRadius: 14,
              padding: "16px",
              display: "flex",
              flexDirection: "column",
              gap: 10
            }}>
              <span style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", color: "var(--color-text-secondary)" }}>
                Hoặc nạp nhanh dữ liệu mẫu
              </span>
              <p style={{ fontSize: 11, color: "var(--color-text-secondary)", margin: 0, lineHeight: 1.4 }}>
                Bấm nạp nhanh dữ liệu lịch trình bay VJ mẫu có sẵn trong hệ thống mà không cần file.
              </p>
              <button
                onClick={handleSeedDatabase}
                disabled={seedLoading}
                style={{
                  padding: "8px 0",
                  borderRadius: 8,
                  border: "none",
                  background: "var(--color-background-success)",
                  color: "var(--color-text-success)",
                  fontSize: 11,
                  fontWeight: 700,
                  cursor: seedLoading ? "not-allowed" : "pointer",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 6
                }}
              >
                {seedLoading ? (
                  <><span style={{ width: 10, height: 10, border: "2px solid var(--color-text-success)", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.8s linear infinite" }} /> Đang Seed...</>
                ) : (
                  <><IconLightning /> Seed dữ liệu mẫu VJ</>
                )}
              </button>
            </div>
          )}

          {saveResult && (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <button onClick={onGoToOverview}
                style={{
                  padding: "11px 0", borderRadius: 10, border: "none",
                  background: "var(--color-text-info)",
                  color: "#fff",
                  fontSize: 12, fontWeight: 700, cursor: "pointer",
                  display: "flex", alignItems: "center",
                  justifyContent: "center", gap: 8,
                  boxShadow: "0 2px 4px rgba(0,0,0,0.05)"
                }}>
                <IconCheck /> Đi đến danh sách chuyến bay
              </button>

              <button onClick={handleReset}
                style={{
                  padding: "9px 0", borderRadius: 10,
                  border: "0.5px solid var(--color-border-secondary)",
                  background: "transparent", color: "var(--color-text-secondary)",
                  fontSize: 12, cursor: "pointer", fontWeight: 600,
                  display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
                }}>
                <IconRefresh /> Nạp file khác
              </button>
            </div>
          )}

          {/* File Schema Help Panel */}
          <div className="glass-panel" style={{
            borderRadius: 14,
            padding: "14px 16px",
            fontSize: 11,
            color: "var(--color-text-secondary)",
            lineHeight: 1.8,
          }}>
            <div style={{ fontWeight: 700, color: "var(--color-text-primary)", marginBottom: 6, fontSize: 10, textTransform: "uppercase", letterSpacing: ".04em" }}>
              Cấu trúc file hợp lệ
            </div>
            <div style={{ marginBottom: 6 }}>
              <span style={{ color: "var(--color-text-info)", fontWeight: 700 }}>Cột bắt buộc:</span>
              <div style={{ marginTop: 2, paddingLeft: 8, borderLeft: "2.5px solid var(--color-border-info)" }}>
                dtm_Local_ETD_Date, str_Dep, str_Arr, str_Fare_Category_Ident, mny_GL_Charges_Total, LF_by_date
              </div>
            </div>
            <div>
              <span style={{ color: "var(--color-text-secondary)", fontWeight: 700 }}>Cột tùy chọn:</span>
              <div style={{ marginTop: 2, paddingLeft: 8, borderLeft: "2.5px solid var(--color-border-tertiary)" }}>
                lead_time_days, booking_velocity_3d/7d, Weekday, IsHoliday, lng_Capacity, lng_fuel, fare_family
              </div>
            </div>
          </div>
        </div>        {/* RIGHT: Status and Results */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16, overflow: "auto" }}>
          
          {saveError && (
            <div style={{ padding: "14px 16px", background: "var(--color-background-danger)", borderRadius: 12, color: "var(--color-text-danger)", fontSize: 12, display: "flex", alignItems: "flex-start", gap: 8, lineHeight: 1.6, border: "1px solid var(--color-border-danger)" }}>
              <IconWarning />
              <div>
                <div style={{ fontWeight: 700, marginBottom: 2 }}>Lỗi lưu cơ sở dữ liệu!</div>
                <div>{saveError}</div>
              </div>
            </div>
          )}

          {seedError && (
            <div style={{ padding: "14px 16px", background: "var(--color-background-danger)", borderRadius: 12, color: "var(--color-text-danger)", fontSize: 12, display: "flex", alignItems: "flex-start", gap: 8, lineHeight: 1.6, border: "1px solid var(--color-border-danger)" }}>
              <IconWarning />
              <div>
                <div style={{ fontWeight: 700, marginBottom: 2 }}>Seed dữ liệu thất bại!</div>
                <div>{seedError}</div>
              </div>
            </div>
          )}

          {/* Seeding Success Banner */}
          {seedResult && (
            <div className="glass-panel" style={{
              borderRadius: 16,
              padding: "24px 20px",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              textAlign: "center",
              gap: 16,
            }}>
              <div style={{ width: 44, height: 44, borderRadius: "50%", background: "var(--color-background-success)", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--color-text-success)", fontSize: 20 }}>
                <IconCheck />
              </div>
              <div>
                <h4 style={{ margin: 0, fontSize: 14, fontWeight: 700, color: "var(--color-text-primary)" }}>Seed dữ liệu mẫu thành công!</h4>
                <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.7, margin: "6px 0 14px 0" }}>
                  Đã thêm thành công <strong>{seedResult.rows_inserted}</strong> dòng mới và cập nhật <strong>{seedResult.rows_updated}</strong> dòng lịch trình bay VJ vào SQL Server.
                </p>
                <button onClick={onGoToOverview}
                  style={{
                    padding: "8px 20px", borderRadius: 8, border: "none",
                    background: "var(--color-text-info)", color: "#fff",
                    fontSize: 12, fontWeight: 700, cursor: "pointer",
                    boxShadow: "0 1px 3px rgba(0,0,0,0.05)"
                  }}>
                  Xem chuyến bay nạp được
                </button>
              </div>
            </div>
          )}

          {/* DB Commit Result Banner */}
          {saveResult && (
            <div className="glass-panel" style={{
              borderRadius: 16,
              padding: "24px 20px",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              textAlign: "center",
              gap: 16,
            }}>
              <div style={{ width: 44, height: 44, borderRadius: "50%", background: "var(--color-background-success)", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--color-text-success)", fontSize: 18 }}>
                <IconCheck />
              </div>
              <div>
                <h4 style={{ margin: 0, fontSize: 14, fontWeight: 700, color: "var(--color-text-primary)" }}>Dữ liệu đã được lưu vĩnh viễn!</h4>
                <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.7, margin: "6px 0 14px 0" }}>
                  Ghi thành công <strong>{saveResult.rows_inserted}</strong> dòng mới và cập nhật <strong>{saveResult.rows_updated}</strong> dòng lịch trình bay từ file <strong>{saveResult.filename || file?.name}</strong> vào SQL Server.
                </p>
                <button onClick={onGoToOverview}
                  style={{
                    padding: "8px 20px", borderRadius: 8, border: "none",
                    background: "var(--color-text-info)", color: "#fff",
                    fontSize: 12, fontWeight: 700, cursor: "pointer",
                    boxShadow: "0 1px 3px rgba(0,0,0,0.05)"
                  }}>
                  Xem danh sách chuyến bay
                </button>
              </div>
            </div>
          )}

          {/* Loading States */}
          {saveLoading && (
            <div className="glass-panel" style={{
              flex: 1, display: "flex", flexDirection: "column",
              alignItems: "center", justifyContent: "center", gap: 12, padding: "48px 20px",
              borderRadius: 16, textAlign: "center",
            }}>
              <span style={{ width: 36, height: 36, border: "3px solid var(--color-border-info)", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.8s linear infinite" }} />
              <div style={{ fontSize: 14, fontWeight: 700, color: "var(--color-text-primary)", marginTop: 6 }}>Đang ghi dữ liệu vào SQL Server...</div>
              <div style={{ fontSize: 11, color: "var(--color-text-secondary)" }}>Hệ thống đang lưu trữ và đồng bộ hóa dữ liệu lịch trình bay của bạn. Vui lòng không đóng trang.</div>
            </div>
          )}

          {/* Seed Loading States */}
          {seedLoading && (
            <div className="glass-panel" style={{
              flex: 1, display: "flex", flexDirection: "column",
              alignItems: "center", justifyContent: "center", gap: 12, padding: "48px 20px",
              borderRadius: 16, textAlign: "center",
            }}>
              <span style={{ width: 36, height: 36, border: "3px solid var(--color-background-success)", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.8s linear infinite" }} />
              <div style={{ fontSize: 14, fontWeight: 700, color: "var(--color-text-primary)", marginTop: 6 }}>Đang nạp dữ liệu mẫu VJ...</div>
              <div style={{ fontSize: 11, color: "var(--color-text-secondary)" }}>Đang khởi tạo lịch trình bay mẫu có sẵn trong hệ thống.</div>
            </div>
          )}

          {/* File Selected but not uploaded yet */}
          {file && !saveResult && !saveLoading && (
            <div className="glass-panel" style={{
              flex: 1, display: "flex", flexDirection: "column",
              alignItems: "center", justifyContent: "center", gap: 16, padding: "48px 20px",
              borderRadius: 16, textAlign: "center",
            }}>
              <span style={{ color: "var(--color-text-info)", display: "flex" }}><IconFileText /></span>
              <div>
                <div style={{ fontSize: 14, fontWeight: 700, color: "var(--color-text-primary)", marginBottom: 6 }}>Tệp tin sẵn sàng nạp</div>
                <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.7, maxWidth: 360, margin: "0 auto 16px auto" }}>
                  File <strong>{file.name}</strong> ({(file.size / 1024).toFixed(1)} KB) đã sẵn sàng. Hãy bấm nút <strong>Tải lên & Lưu vào Database</strong> ở bảng bên trái để hoàn tất.
                </p>
              </div>
            </div>
          )}

          {/* Empty state when no file */}
          {!file && !seedResult && !saveResult && !saveLoading && !seedLoading && (
            <div className="glass-panel" style={{
              flex: 1, display: "flex", flexDirection: "column",
              alignItems: "center", justifyContent: "center", gap: 16, padding: "48px 20px",
              borderRadius: 16, textAlign: "center",
            }}>
              <span style={{ color: "var(--color-text-secondary)", display: "flex" }}><IconFolder /></span>
              <div>
                <div style={{ fontSize: 14, fontWeight: 700, color: "var(--color-text-primary)", marginBottom: 6 }}>Chưa chọn tệp dữ liệu</div>
                <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.7, maxWidth: 360, margin: 0 }}>
                  Kéo thả tệp CSV hoặc Excel chứa lịch trình bay vào vùng bên trái và lưu vào cơ sở dữ liệu.
                </p>
              </div>
            </div>
          )}

        </div>
      </div>
    </div>
  );
}
