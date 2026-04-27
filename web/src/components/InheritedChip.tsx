import styles from "./InheritedChip.module.css";

interface Props {
  label: string;
  onClick?: () => void;
}

export function InheritedChip({ label, onClick }: Props) {
  return (
    <span
      className={`${styles.chip} ${onClick ? styles.clickable : ""}`}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => e.key === "Enter" && onClick() : undefined}
    >
      ↳ {label}
    </span>
  );
}
