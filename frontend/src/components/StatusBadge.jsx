import { IconTrendUp, IconTrendDown, IconTrendNeutral, IconTrendMid } from "./icons";

const STATUS_CONFIG = {
  high: { cls: "success", Icon: IconTrendUp,      label: "Increase"  },
  ok:   { cls: "info",    Icon: IconTrendNeutral,  label: "Optimize" },
  mid:  { cls: "warning", Icon: IconTrendMid,      label: "Follow up" },
  low:  { cls: "danger",  Icon: IconTrendDown,     label: "Increase"  },
};

export function StatusBadge({ status }) {
  const c = STATUS_CONFIG[status] || STATUS_CONFIG.ok;
  const Icon = c.Icon;
  return (
    <span style={{
      display: "inline-flex",
      alignItems: "center",
      gap: 4,
      padding: "2px 8px",
      borderRadius: 20,
      fontSize: 10,
      fontWeight: 500,
      background: `var(--color-background-${c.cls})`,
      color: `var(--color-text-${c.cls})`,
    }}>
      <Icon />
      {c.label}
    </span>
  );
}
