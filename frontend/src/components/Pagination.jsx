import { IconChevronLeft, IconChevronRight } from "./icons";

export function Pagination({ page, total, pageSize, onChange }) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  if (total === 0) return null;
  const pages = [];
  const maxVisible = 5;
  let start = Math.max(1, page - Math.floor(maxVisible / 2));
  let end = Math.min(totalPages, start + maxVisible - 1);
  if (end - start < maxVisible - 1) start = Math.max(1, end - maxVisible + 1);
  for (let i = start; i <= end; i++) pages.push(i);

  const btnStyle = (isActive) => ({
    width: 26, height: 26, borderRadius: 6,
    border: `0.5px solid ${isActive ? "var(--color-border-info)" : "var(--color-border-tertiary)"}`,
    background: isActive ? "var(--color-background-info)" : "transparent",
    color: isActive ? "var(--color-text-info)" : "var(--color-text-secondary)",
    cursor: "pointer", fontSize: 11, fontWeight: isActive ? 600 : 400,
  });

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 4, justifyContent: "flex-end" }}>
      <span style={{ fontSize: 11, color: "var(--color-text-secondary)", marginRight: 4 }}>
        {((page - 1) * pageSize) + 1}–{Math.min(page * pageSize, total)} / {total}
      </span>
      <button
        onClick={() => onChange(page - 1)}
        disabled={page === 1}
        style={{
          ...btnStyle(false), display: "flex", alignItems: "center", justifyContent: "center",
          cursor: page === 1 ? "not-allowed" : "pointer",
          color: page === 1 ? "var(--color-border-tertiary)" : "var(--color-text-secondary)",
          background: "transparent", border: "0.5px solid var(--color-border-tertiary)",
        }}
      >
        <IconChevronLeft />
      </button>
      {pages.map(p => (
        <button key={p} onClick={() => onChange(p)} style={btnStyle(p === page)}>
          {p}
        </button>
      ))}
      <button
        onClick={() => onChange(page + 1)}
        disabled={page === totalPages}
        style={{
          ...btnStyle(false), display: "flex", alignItems: "center", justifyContent: "center",
          cursor: page === totalPages ? "not-allowed" : "pointer",
          color: page === totalPages ? "var(--color-border-tertiary)" : "var(--color-text-secondary)",
          background: "transparent", border: "0.5px solid var(--color-border-tertiary)",
        }}
      >
        <IconChevronRight />
      </button>
    </div>
  );
}
