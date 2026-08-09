export type ClassicalIconName =
  | "character"
  | "persona"
  | "world"
  | "preset"
  | "bookmark"
  | "checkpoint"
  | "settings"
  | "folio";

export function ClassicalIcon({ name, className = "" }: { name: ClassicalIconName; className?: string }) {
  const common = {
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.25,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };

  return (
    <svg className={`classical-icon ${className}`} viewBox="0 0 24 24" aria-hidden="true" focusable="false" {...common}>
      {name === "character" && <>
        <path d="M12 3.2c-1.55 0-2.45 1.02-2.45 2.4 0 1.03.52 1.82 1.35 2.22l-2.66 4.06h7.52L13.1 7.82c.83-.4 1.35-1.19 1.35-2.22 0-1.38-.9-2.4-2.45-2.4Z" />
        <path d="M8.24 11.88c-.2 2.42.4 4.18 1.78 5.3h3.96c1.38-1.12 1.98-2.88 1.78-5.3M8.16 17.18h7.68M6.9 20.8h10.2l-1.26-3.62H8.16L6.9 20.8Z" />
        <path d="M12 3.2V1.8M10.9 2.45h2.2" />
      </>}
      {name === "persona" && <>
        <circle cx="12" cy="12" r="9.15" />
        <circle cx="12" cy="12" r="7.15" opacity=".48" />
        <path d="M14.7 16.5c-.78.5-1.7.76-2.7.76-2.9 0-5.05-2.16-5.05-5.2 0-2.77 1.86-5.03 4.54-5.27 1.65-.15 3.15.56 4.08 1.72-1.08.1-1.73.58-1.73 1.34 0 .82.72 1.08.72 1.8 0 .48-.3.87-.92 1.18.42.42.64.92.64 1.47 0 .88-.48 1.62-1.36 2.17" />
      </>}
      {name === "world" && <>
        <path d="M3.2 5.5c3.35-.7 6.27.04 8.8 2.18v11.04c-2.53-2.14-5.45-2.88-8.8-2.18V5.5ZM20.8 5.5c-3.35-.7-6.27.04-8.8 2.18v11.04c2.53-2.14 5.45-2.88 8.8-2.18V5.5Z" />
        <path d="M5.65 8.25c1.7-.12 3.12.25 4.28 1.06M14.07 9.31c1.16-.81 2.58-1.18 4.28-1.06M5.65 11.2c1.7-.12 3.12.25 4.28 1.06M14.07 12.26c1.16-.81 2.58-1.18 4.28-1.06" opacity=".62" />
      </>}
      {name === "preset" && <>
        <path d="M12 2.35c.68 5.8 3.85 8.97 9.65 9.65-5.8.68-8.97 3.85-9.65 9.65C11.32 15.85 8.15 12.68 2.35 12 8.15 11.32 11.32 8.15 12 2.35Z" />
        <path d="M12 7.7c.3 2.58 1.72 4 4.3 4.3-2.58.3-4 1.72-4.3 4.3-.3-2.58-1.72-4-4.3-4.3 2.58-.3 4-1.72 4.3-4.3Z" opacity=".5" />
      </>}
      {name === "bookmark" && <>
        <path d="M7.1 3.25h9.8v17.5L12 17.55 7.1 20.75V3.25Z" />
        <path d="M9.3 6.4h5.4" opacity=".58" />
      </>}
      {name === "checkpoint" && <>
        <path d="m12 2.7 8.35 9.3L12 21.3 3.65 12 12 2.7Z" />
        <circle cx="12" cy="12" r="3.1" />
        <path d="M12 6.5v2M12 15.5v2M6.5 12h2M15.5 12h2" opacity=".55" />
      </>}
      {name === "settings" && <>
        <circle cx="12" cy="12" r="5.65" />
        <circle cx="12" cy="12" r="1.75" />
        <path d="M12 2.3v2.25M12 19.45v2.25M2.3 12h2.25M19.45 12h2.25M5.15 5.15l1.6 1.6M17.25 17.25l1.6 1.6M18.85 5.15l-1.6 1.6M6.75 17.25l-1.6 1.6" />
      </>}
      {name === "folio" && <>
        <rect x="4" y="3.2" width="16" height="17.6" rx=".8" />
        <path d="M8 3.2v17.6M11 7h5.6M11 10h5.6M11 13h4.1M11 17.1h5.6" opacity=".7" />
      </>}
    </svg>
  );
}
