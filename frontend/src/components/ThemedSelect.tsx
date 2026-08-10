import { useEffect, useRef, useState } from "react";

type SelectOption<T extends string> = {
  value: T;
  label: string;
};

export function ThemedSelect<T extends string>(props: {
  value: T;
  options: SelectOption<T>[];
  onChange: (value: T) => void;
  ariaLabel: string;
  disabled?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const selected = props.options.find((item) => item.value === props.value) ?? props.options[0];

  useEffect(() => {
    if (!open) return;
    const close = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [open]);

  return (
    <div className={`themed-select${open ? " open" : ""}${props.className ? ` ${props.className}` : ""}`} ref={root}>
      <button
        type="button"
        className="themed-select-trigger"
        aria-label={props.ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={props.disabled}
        onClick={() => setOpen((value) => !value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            const current = Math.max(0, props.options.findIndex((item) => item.value === props.value));
            const offset = event.key === "ArrowDown" ? 1 : -1;
            const next = (current + offset + props.options.length) % props.options.length;
            props.onChange(props.options[next].value);
          }
        }}
      >
        <span>{selected?.label ?? "请选择"}</span><i aria-hidden="true" />
      </button>
      {open && <div className="themed-select-menu" role="listbox" aria-label={props.ariaLabel}>
        {props.options.map((item) => <button
          type="button"
          role="option"
          aria-selected={item.value === props.value}
          className={item.value === props.value ? "selected" : ""}
          key={item.value}
          onClick={() => { props.onChange(item.value); setOpen(false); }}
        >{item.label}</button>)}
      </div>}
    </div>
  );
}
