// Apple SF Symbols Inspired SVG Icons
// Features: Monoline design, rounded line caps, 1.5px/1.6px stroke defaults, clean iOS geometries.

import React from "react";

export const IconTrendUp = ({ size = 10, strokeWidth = 1.8, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M2 8L8 2M4.5 2H8V5.5" />
  </svg>
);

export const IconTrendDown = ({ size = 10, strokeWidth = 1.8, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M2 2L8 8M4.5 8H8V4.5" />
  </svg>
);

export const IconTrendNeutral = ({ size = 10, strokeWidth = 1.8, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M1.5 5H8.5" />
  </svg>
);

export const IconTrendMid = ({ size = 10, strokeWidth = 1.8, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M1.5 7.5Q5 4 8.5 4.5" />
  </svg>
);

export const IconChevronUp = ({ size = 12, strokeWidth = 1.6, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M2 8L6 4L10 8" />
  </svg>
);

export const IconChevronDown = ({ size = 12, strokeWidth = 1.6, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M2 4L6 8L10 4" />
  </svg>
);

export const IconSearch = ({ size = 14, strokeWidth = 1.5, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <circle cx="6.5" cy="6.5" r="4.5" />
    <path d="M10 10L14.5 14.5" />
  </svg>
);

export const IconRefresh = ({ size = 13, strokeWidth = 1.5, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M2.5 8A5.5 5.5 0 1 1 8 13.5" />
    <path d="M2.5 4V8H6.5" />
  </svg>
);

export const IconPlus = ({ size = 14, strokeWidth = 2, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M8 3V13M3 8H13" />
  </svg>
);

export const IconMinus = ({ size = 14, strokeWidth = 2, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M3 8H13" />
  </svg>
);

export const IconCheck = ({ size = 14, strokeWidth = 2, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M3.5 8L6.5 11L12.5 4.5" />
  </svg>
);

export const IconArrowRight = ({ size = 14, strokeWidth = 1.5, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M2 8H14M9 3L14 8L9 13" />
  </svg>
);

export const IconChevronLeft = ({ size = 12, strokeWidth = 1.5, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M8 2.5L4.5 6L8 9.5" />
  </svg>
);

export const IconChevronRight = ({ size = 12, strokeWidth = 1.5, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M4 2.5L7.5 6L4 9.5" />
  </svg>
);

export const IconPlane = ({ size = 16, strokeWidth = 1.5, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M21 15.75L13 11V3.5A1.5 1.5 0 0 0 11.5 2h0A1.5 1.5 0 0 0 10 3.5V11L2 15.75v1.5l8-2.5V19.5l-2.5 2v1l4-1.25 4 1.25v-1l-2.5-2V14.75l8 2.5v-1.5z" fill="currentColor" />
  </svg>
);

export const IconCalendar = ({ size = 13, strokeWidth = 1.5, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <rect x="2" y="3.5" width="12" height="11" rx="2" />
    <path d="M5 2V5M11 2V5M2 7H14" />
  </svg>
);

export const IconMapPin = ({ size = 13, strokeWidth = 1.5, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M8 2A4.5 4.5 0 0 0 3.5 6.5c0 3.5 4.5 8 4.5 8s4.5-4.5 4.5-8A4.5 4.5 0 0 0 8 2z" />
    <circle cx="8" cy="6.5" r="1.5" />
  </svg>
);

export const IconUpload = ({ size = 13, strokeWidth = 1.5, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M3 8V13.5A1.5 1.5 0 0 0 4.5 15H11.5A1.5 1.5 0 0 0 13 13.5V8" />
    <path d="M8 12V2M5 5.5L8 2.5L11 5.5" />
  </svg>
);

export const IconDollar = ({ size = 13, strokeWidth = 1.5, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M8 1.5v13M5.5 4h5a2 2 0 0 1 0 4h-5a2 2 0 0 0 0 4h5" />
  </svg>
);

export const IconUsers = ({ size = 13, strokeWidth = 1.5, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <circle cx="6" cy="5.5" r="2.25" />
    <path d="M1.5 13c0-2.5 2-4 4.5-4s4.5 1.5 4.5 4" />
    <circle cx="11.5" cy="7" r="1.75" />
    <path d="M8.5 13c.5-1.5 1.5-2.2 3-2.2s2.5.7 3 2.2" />
  </svg>
);

export const IconWarning = ({ size = 14, strokeWidth = 1.5, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M8 2.2L1.5 13.5A1 1 0 0 0 2.4 15H13.6a1 1 0 0 0 .9-1.5L8 2.2z" strokeLinejoin="round" />
    <path d="M8 6V9.5M8 11.8v.2" />
  </svg>
);

export const IconSort = ({ size = 12, strokeWidth = 1.5, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M3 4H13M4.5 8H11.5M6 12H10" />
  </svg>
);

export const IconBot = ({ size = 14, strokeWidth = 1.5, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    {/* SF Symbol Sparkles - Apple Intelligence Style */}
    <path d="M9.5 2L11 6.5L15.5 8L11 9.5L9.5 14L8 9.5L3.5 8L8 6.5L9.5 2Z" fill="currentColor" stroke="none" />
    <path d="M17 11L18 14L21 15L18 16L17 19L16 16L13 15L16 14L17 11Z" fill="currentColor" stroke="none" />
    <path d="M5.5 13.5L6 15L7.5 15.5L6 16L5.5 17.5L5 16L3.5 15.5L5 15L5.5 13.5Z" fill="currentColor" stroke="none" />
  </svg>
);

export const IconCpu = ({ size = 14, strokeWidth = 1.5, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <rect x="6" y="6" width="12" height="12" rx="2.5" />
    <rect x="10" y="10" width="4" height="4" rx="0.5" />
    <path d="M9 2V6M15 2V6M9 18V22M15 18V22M2 9H6M2 15H6M18 9H22M18 15H22" />
  </svg>
);

export const IconTicket = ({ size = 13, strokeWidth = 1.5, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M3 8a3 3 0 0 0 0 6v3a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V14a3 3 0 0 0 0-6V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v3z" />
    <path d="M12 3v18" strokeDasharray="3 3" />
  </svg>
);

export const IconLightning = ({ size = 13, strokeWidth = 1.5, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" fill="none" />
  </svg>
);

export const IconFolder = ({ size = 14, strokeWidth = 1.5, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M20 20H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h4l2 3h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2z" />
  </svg>
);

export const IconFileText = ({ size = 14, strokeWidth = 1.5, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
    <polyline points="14 2 14 8 20 8" />
    <line x1="16" y1="13" x2="8" y2="13" />
    <line x1="16" y1="17" x2="8" y2="17" />
    <line x1="10" y1="9" x2="8" y2="9" />
  </svg>
);

export const IconInbox = ({ size = 14, strokeWidth = 1.5, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M22 12h-6l-2 3h-4l-2-3H2" />
    <path d="M2 12l3-8h14l3 8v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6z" />
  </svg>
);

export const IconDatabase = ({ size = 14, strokeWidth = 1.5, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <ellipse cx="12" cy="5" rx="9" ry="3" />
    <path d="M3 5v6c0 1.66 4 3 9 3s9-1.34 9-3V5" />
    <path d="M3 11v6c0 1.66 4 3 9 3s9-1.34 9-3v-6" />
  </svg>
);

export const IconTrash = ({ size = 13, strokeWidth = 1.5, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    <line x1="10" y1="11" x2="10" y2="17" />
    <line x1="14" y1="11" x2="14" y2="17" />
  </svg>
);

export const IconStar = ({ fill = "currentColor", size = 12, strokeWidth = 1.5, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={fill} stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
  </svg>
);

export const IconSparkles = ({ size = 13, strokeWidth = 1.5, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364-6.364l-.707.707M6.343 17.657l-.707.707m0-12.728l.707.707m11.314 11.314l.707.707" />
  </svg>
);

export const IconChartPie = ({ size = 14, strokeWidth = 1.5, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <circle cx="12" cy="12" r="10" />
    <path d="M12 2v10h10" />
    <path d="M12 12L5 5" />
  </svg>
);

export const IconBriefcase = ({ size = 13, strokeWidth = 1.5, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <rect x="2" y="7" width="20" height="14" rx="2" ry="2" />
    <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
  </svg>
);

// --- NEW APPLE ICONS ---

export const IconOverview = ({ size = 14, strokeWidth = 1.5, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    {/* Apple Widget/Overview layout */}
    <rect x="3" y="3" width="7" height="9" rx="1.5" />
    <rect x="14" y="3" width="7" height="5" rx="1.5" />
    <rect x="3" y="16" width="7" height="5" rx="1.5" />
    <rect x="14" y="12" width="7" height="9" rx="1.5" />
  </svg>
);

export const IconOptimizer = ({ size = 14, strokeWidth = 1.5, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    {/* Apple Slider.horizontal.3 Symbol */}
    <line x1="3" y1="5" x2="21" y2="5" />
    <line x1="3" y1="12" x2="21" y2="12" />
    <line x1="3" y1="19" x2="21" y2="19" />
    <circle cx="8" cy="5" r="2" fill="#fff" />
    <circle cx="16" cy="12" r="2" fill="#fff" />
    <circle cx="10" cy="19" r="2" fill="#fff" />
  </svg>
);

export const IconSimulator = ({ size = 14, strokeWidth = 1.5, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    {/* Apple Line Chart/Gauge Simulator Symbol */}
    <path d="M3 3v18h18" />
    <path d="M18.5 7.5L13.5 12.5L9.5 8.5L4.5 13.5" />
    <circle cx="18.5" cy="7.5" r="1" fill="currentColor" />
    <circle cx="13.5" cy="12.5" r="1" fill="currentColor" />
    <circle cx="9.5" cy="8.5" r="1" fill="currentColor" />
  </svg>
);

export const IconClose = ({ size = 18, strokeWidth = 1.8, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M18 6L6 18M6 6l12 12" />
  </svg>
);

export const IconEllipsisVertical = ({ size = 16, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" {...props}>
    <circle cx="12" cy="5" r="1.5" />
    <circle cx="12" cy="12" r="1.5" />
    <circle cx="12" cy="19" r="1.5" />
  </svg>
);

export const IconLoader = ({ size = 20, strokeWidth = 2, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" {...props}>
    <path d="M12 3a9 9 0 1 1-9 9" />
  </svg>
);

export const IconAlertCircle = ({ size = 14, strokeWidth = 1.5, ...props }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...props}>
    <circle cx="12" cy="12" r="10" />
    <path d="M12 8v5M12 16v.01" />
  </svg>
);
