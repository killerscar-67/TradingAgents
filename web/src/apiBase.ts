const explicitApiBase = import.meta.env.VITE_API_BASE_URL as string | undefined;

function defaultHttpBase(): string {
  if (typeof window === "undefined") return "";
  if (window.location.port === "5173") {
    return `${window.location.protocol}//${window.location.hostname}:8000`;
  }
  return "";
}

export function apiUrl(path: string): string {
  const base = explicitApiBase ?? defaultHttpBase();
  return `${base}${path}`;
}

export function apiWsUrl(path: string): string {
  const httpUrl = new URL(apiUrl(path), window.location.origin);
  httpUrl.protocol = httpUrl.protocol === "https:" ? "wss:" : "ws:";
  return httpUrl.toString();
}
