import type { ReactNode } from "react";
import styles from "./Dialog.module.css";

interface Props {
  open: boolean;
  title: string;
  onConfirm: () => void;
  onCancel: () => void;
  children: ReactNode;
}

export function Dialog({ open, title, onConfirm, onCancel, children }: Props) {
  if (!open) return null;

  return (
    <div className={styles.overlay} role="dialog" aria-modal="true" aria-labelledby="dialog-title">
      <div className={styles.panel}>
        <h2 className={styles.title} id="dialog-title">{title}</h2>
        <div className={styles.body}>{children}</div>
        <div className={styles.actions}>
          <button className={styles.cancelBtn} onClick={onCancel}>Cancel</button>
          <button className={styles.confirmBtn} onClick={onConfirm}>Confirm</button>
        </div>
      </div>
    </div>
  );
}
