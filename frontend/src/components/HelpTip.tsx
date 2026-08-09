import { useState } from "react";
import { createPortal } from "react-dom";

const POPUP_WIDTH = 260;

export function HelpTip({ text }: { text: string }) {
  const [position, setPosition] = useState<{ left: number; top: number; below: boolean } | null>(null);

  function open(target: HTMLElement) {
    const rect = target.getBoundingClientRect();
    const left = Math.min(
      window.innerWidth - POPUP_WIDTH - 12,
      Math.max(12, rect.left + rect.width / 2 - POPUP_WIDTH / 2),
    );
    const below = rect.top < 100;
    setPosition({ left, top: below ? rect.bottom + 8 : rect.top - 8, below });
  }

  return (
    <>
      <span
        className="help-tip"
        tabIndex={0}
        aria-label={text}
        onMouseEnter={(event) => open(event.currentTarget)}
        onMouseLeave={() => setPosition(null)}
        onFocus={(event) => open(event.currentTarget)}
        onBlur={() => setPosition(null)}
      >?</span>
      {position && createPortal(
        <span
          className={`help-tip-popup${position.below ? " below" : ""}`}
          role="tooltip"
          style={{ left: position.left, top: position.top, width: POPUP_WIDTH }}
        >{text}</span>,
        document.body,
      )}
    </>
  );
}
