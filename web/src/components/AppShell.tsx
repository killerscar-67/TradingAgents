import type { ReactNode } from "react";
import { Sidebar } from "./Sidebar";
import styles from "./AppShell.module.css";

interface Props {
  children: ReactNode;
}

export function AppShell({ children }: Props) {
  return (
    <div className={styles.shell}>
      <Sidebar />
      <div className={styles.content}>{children}</div>
    </div>
  );
}
