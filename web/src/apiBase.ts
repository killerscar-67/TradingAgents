const explicitApiBase = import.meta.env.VITE_API_BASE_URL as string | undefined;

function defaultHttpBase(): string {
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
