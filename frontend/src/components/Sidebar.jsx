import { NavLink, useLocation } from "react-router-dom";
import { useIsMobile } from "../hooks/useIsMobile";
import {
  IconChartPie,
  IconOverview,
  IconOptimizer,
  IconSimulator,
  IconMapPin,
  IconUpload,
  IconBot,
  IconPlane
} from "./icons";

const NAV = [
  { to: "/",          Icon: IconChartPie,  label: "Dashboard" },
  { to: "/overview",   Icon: IconOverview,  label: "Overview"  },
  { to: "/optimizer",  Icon: IconOptimizer, label: "Optimizer" },
  { to: "/simulator",  Icon: IconSimulator, label: "Simulator" },
  { to: "/routes",     Icon: IconMapPin,    label: "Routes"    },
  { to: "/upload",     Icon: IconUpload,    label: "Upload"    },
  { to: "/copilot",    Icon: IconBot,       label: "Copilot"   },
];

export function Sidebar() {
  const location = useLocation();
  const isMobile = useIsMobile();

  // Mobile: bottom navigation bar thay cho rail dọc bên trái
  if (isMobile) {
    return (
      <div
        className="glass-panel"
        style={{
          position: "fixed",
          bottom: 0,
          left: 0,
          right: 0,
          height: 58,
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-around",
          padding: "0 6px",
          paddingBottom: "env(safe-area-inset-bottom)",
          borderRadius: "18px 18px 0 0",
          boxShadow: "0 -6px 24px rgba(0, 0, 0, 0.07)",
          zIndex: 500,
        }}
      >
        {NAV.map(n => {
          const isActive = n.to === "/" ? location.pathname === "/" : location.pathname.startsWith(n.to);
          return (
            <NavLink
              key={n.to}
              to={n.to}
              title={n.label}
              className={isActive ? "nav-active-drop" : ""}
              style={{
                width: 40,
                height: 40,
                borderRadius: "var(--border-radius-md)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                textDecoration: "none",
                color: isActive ? "var(--color-text-info)" : "var(--color-text-secondary)",
              }}
            >
              <n.Icon size={18} />
            </NavLink>
          );
        })}
      </div>
    );
  }

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
        <IconPlane size={18} style={{ color: "var(--color-text-info)" }} />
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
            <n.Icon size={16} />
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
