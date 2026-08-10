export type ClassicalIconName =
  | "character"
  | "persona"
  | "world"
  | "preset"
  | "extension"
  | "bookmark"
  | "checkpoint"
  | "settings"
  | "folio"
  | "nib";

export function ClassicalIcon({ name, className = "" }: { name: ClassicalIconName; className?: string }) {
  const common = {
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.45,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };

  return (
    <svg className={`classical-icon ${className}`} viewBox="0 0 24 24" aria-hidden="true" focusable="false" {...common}>
      {name === "character" && <>
        <path d="M12 3.2c-1.55 0-2.45 1.02-2.45 2.4 0 1.03.52 1.82 1.35 2.22l-2.66 4.06h7.52L13.1 7.82c.83-.4 1.35-1.19 1.35-2.22 0-1.38-.9-2.4-2.45-2.4Z" />
        <path d="M8.24 11.88c-.2 2.42.4 4.18 1.78 5.3h3.96c1.38-1.12 1.98-2.88 1.78-5.3M8.16 17.18h7.68M6.9 20.8h10.2l-1.26-3.62H8.16L6.9 20.8Z" />
        <path d="M12 3.2V1.8M10.9 2.45h2.2" />
        <path d="M8.5 19.05h7M9.25 14.15h5.5" opacity=".38" />
      </>}
      {name === "persona" && <>
        <circle cx="12" cy="12" r="9.15" />
        <circle cx="12" cy="12" r="7.15" opacity=".48" />
        <path d="M14.7 16.5c-.78.5-1.7.76-2.7.76-2.9 0-5.05-2.16-5.05-5.2 0-2.77 1.86-5.03 4.54-5.27 1.65-.15 3.15.56 4.08 1.72-1.08.1-1.73.58-1.73 1.34 0 .82.72 1.08.72 1.8 0 .48-.3.87-.92 1.18.42.42.64.92.64 1.47 0 .88-.48 1.62-1.36 2.17" />
        <path d="M12 1.2v1.65M12 21.15v1.65M1.2 12h1.65M21.15 12h1.65" opacity=".58" />
      </>}
      {name === "world" && <>
        <path d="M3.2 5.5c3.35-.7 6.27.04 8.8 2.18v11.04c-2.53-2.14-5.45-2.88-8.8-2.18V5.5ZM20.8 5.5c-3.35-.7-6.27.04-8.8 2.18v11.04c2.53-2.14 5.45-2.88 8.8-2.18V5.5Z" />
        <path d="M5.65 8.25c1.7-.12 3.12.25 4.28 1.06M14.07 9.31c1.16-.81 2.58-1.18 4.28-1.06M5.65 11.2c1.7-.12 3.12.25 4.28 1.06M14.07 12.26c1.16-.81 2.58-1.18 4.28-1.06" opacity=".62" />
        <path d="M5.65 14.1c1.55-.08 2.88.25 4.05.98M14.3 15.08c1.17-.73 2.5-1.06 4.05-.98" opacity=".35" />
      </>}
      {name === "preset" && <>
        <path d="M4.05 20.15c3.3-4.1 6.46-7.43 10.86-11.67" />
        <path d="M7.05 16.7c-1.02-3.62.02-8.75 10.83-13.28.74 5.85-1.74 10.35-8.32 11.77" />
        <path d="M10.2 12.15c1.72-.28 3.42-.98 5.1-2.08M12.08 8.92c1.26-.17 2.57-.62 3.92-1.35" opacity=".5" />
        <path d="M3.15 21h6.2" />
      </>}
      {name === "extension" && <>
        <path d="M12 3.15 15.15 6.3 12 9.45 8.85 6.3 12 3.15Z" />
        <path d="m6.25 10.05 3.15 3.15-3.15 3.15L3.1 13.2l3.15-3.15ZM17.75 10.05l3.15 3.15-3.15 3.15-3.15-3.15 3.15-3.15Z" />
        <path d="M12 15.05 15.15 18.2 12 21.35 8.85 18.2 12 15.05Z" />
        <path d="m10.05 8.35-2.1 2.1M13.95 8.35l2.1 2.1M9.4 14.7l-1.45 1.45M14.6 14.7l1.45 1.45" opacity=".72" />
        <circle cx="12" cy="12.25" r="1.65" opacity=".58" />
      </>}
      {name === "bookmark" && <>
        <path d="M7.1 3.25h9.8v17.5L12 17.55 7.1 20.75V3.25Z" />
        <path d="M9.3 6.4h5.4" opacity=".58" />
        <circle cx="12" cy="9.4" r="1.45" opacity=".68" />
        <path d="m12 10.85-2.25 3.05L12 12.7l2.25 1.2L12 10.85Z" opacity=".5" />
      </>}
      {name === "checkpoint" && <>
        <path d="m12 2.7 8.35 9.3L12 21.3 3.65 12 12 2.7Z" />
        <circle cx="12" cy="12" r="3.1" />
        <path d="M12 6.5v2M12 15.5v2M6.5 12h2M15.5 12h2" opacity=".55" />
      </>}
      {name === "settings" && <>
        <circle cx="12" cy="12" r="8.85" />
        <ellipse cx="12" cy="12" rx="4.45" ry="8.85" opacity=".72" />
        <ellipse cx="12" cy="12" rx="8.85" ry="4.45" opacity=".72" />
        <circle cx="12" cy="12" r="1.35" fill="currentColor" stroke="none" />
        <path d="M12 1.25v2M12 20.75v2M1.25 12h2M20.75 12h2" />
      </>}
      {name === "folio" && <>
        <rect x="4" y="3.2" width="16" height="17.6" rx=".8" />
        <path d="M8 3.2v17.6M11 7h5.6M11 10h5.6M11 13h4.1M11 17.1h5.6" opacity=".7" />
        <path d="M5.6 5.2h.8M5.6 18.8h.8M18 5.2h.55M18 18.8h.55" opacity=".45" />
      </>}
      {name === "nib" && <>
        <path d="m12 2.6 6.9 6.05-3.42 10.05H8.52L5.1 8.65 12 2.6Z" fill="currentColor" fillOpacity=".15" />
        <path d="M12 3.05v8.1M8.52 18.7l2.62-6.02a1.2 1.2 0 1 1 1.72 0l2.62 6.02M7.55 20.9h8.9" />
        <circle cx="12" cy="11.75" r="1.15" fill="currentColor" stroke="none" />
      </>}
    </svg>
  );
}
