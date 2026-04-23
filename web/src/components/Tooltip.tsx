import { useState } from "react";
import styles from "./Tooltip.module.css";

interface Props {
  text: string;
}

export function Tooltip({ text }: Props) {
  const [open, setOpen] = useState(false);
  return (
    <span className={styles.tooltipWrap}>
      <button
        type="button"
        className={styles.tooltipTrigger}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        aria-label="Help"
      >?</button>
      {open && <span className={styles.tooltipBox} role="tooltip">{text}</span>}
    </span>
  );
}
