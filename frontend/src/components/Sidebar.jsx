import { NavLink, useLocation } from "react-router-dom";

const NAV = [
  { to: "/",          icon: "ti-chart-pie",             label: "Dashboard" },
  { to: "/overview",   icon: "ti-layout-dashboard",      label: "Overview"  },
  { to: "/optimizer",  icon: "ti-adjustments-horizontal", label: "Optimizer" },
  { to: "/simulator",  icon: "ti-chart-line",            label: "Simulator" },
  { to: "/routes",     icon: "ti-map-pin",               label: "Routes"    },
  { to: "/upload",     icon: "ti-upload",                label: "Upload"    },
  { to: "/copilot",    icon: "ti-message-chatbot",       label: "Copilot"   },
];

export function Sidebar() {
  const location = useLocation();
  return (
    <div 
      className="glass-panel"
      style={{
        width: 54,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        padding: "16px 0",
        gap: 6,
        flexShrink: 0,
        margin: "12px 0 12px 12px",
        borderRadius: "24px",
        height: "calc(100vh - 24px)",
        boxShadow: "0 10px 30px rgba(0, 0, 0, 0.05)",
        zIndex: 50,
      }}
    >
      <div style={{
        width: 38, height: 38,
        borderRadius: "50%",
        background: "rgba(222, 31, 38, 0.08)",
        display: "flex", alignItems: "center", justifyContent: "center",
        marginBottom: 10,
        boxShadow: "0 2px 10px rgba(222, 31, 38, 0.1)",
        border: "1px solid rgba(222, 31, 38, 0.15)"
      }}>
        <i className="ti ti-plane" style={{ fontSize: 18, color: "var(--color-text-info)" }} />
      </div>

      {NAV.map(n => {
        const isActive = n.to === "/" ? location.pathname === "/" : location.pathname.startsWith(n.to);
        return (
          <NavLink 
            key={n.to} 
            to={n.to} 
            title={n.label}
            className={isActive ? "nav-active-drop" : "glass-button"}
            style={{
              width: 38, height: 38,
              borderRadius: "var(--border-radius-md)",
              border: "none",
              cursor: "pointer",
              fontSize: 16,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              textDecoration: "none",
              color: isActive ? "var(--color-text-info)" : "var(--color-text-secondary)",
              transition: "all 0.4s cubic-bezier(0.34, 1.56, 0.64, 1)",
            }}
            onMouseEnter={e => {
              if (!isActive) {
                e.currentTarget.style.color = "var(--color-text-primary)";
                e.currentTarget.style.transform = "scale(1.1) translateY(-1px)";
              }
            }}
            onMouseLeave={e => {
              if (!isActive) {
                e.currentTarget.style.color = "var(--color-text-secondary)";
                e.currentTarget.style.transform = "none";
              }
            }}
          >
            <i className={`ti ${n.icon}`} />
          </NavLink>
        );
      })}
      
      <div style={{ flex: 1 }} />
      
      <div style={{
        width: 32, height: 32, borderRadius: "50%",
        background: "rgba(0, 0, 0, 0.03)",
        border: "1px solid var(--color-border-tertiary)",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 10, color: "var(--color-text-secondary)", 
        fontWeight: "bold",
        marginBottom: 8,
        cursor: "pointer",
        transition: "all 0.3s ease"
      }}
      onMouseEnter={e => {
        e.currentTarget.style.transform = "scale(1.1)";
        e.currentTarget.style.color = "var(--color-text-info)";
        e.currentTarget.style.background = "var(--color-background-info)";
        e.currentTarget.style.borderColor = "var(--color-border-info)";
      }}
      onMouseLeave={e => {
        e.currentTarget.style.transform = "none";
        e.currentTarget.style.color = "var(--color-text-secondary)";
        e.currentTarget.style.background = "rgba(0, 0, 0, 0.03)";
        e.currentTarget.style.borderColor = "var(--color-border-tertiary)";
      }}
      >
        AI
      </div>
    </div>
  );
}
