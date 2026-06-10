export const fmt    = n => new Intl.NumberFormat("vi-VN").format(Math.round(n));
export const fmtM   = n => (n / 1e9).toFixed(2) + " ty";
export const fmtPct = (n, dec = 1) => (n >= 0 ? "+" : "") + (+n).toFixed(dec) + "%";

export const getLFColor = lf =>
  lf > 0.7 ? "var(--color-background-success)"
  : lf > 0.5 ? "var(--color-background-warning)"
  : "var(--color-background-danger)";
