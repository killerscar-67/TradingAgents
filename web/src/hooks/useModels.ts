import { useEffect, useState } from "react";

export interface ModelOption {
  label: string;
  value: string;
}

export interface ProviderInfo {
  custom: boolean;
  deep: ModelOption[];
  quick: ModelOption[];
}

export interface ModelCatalog {
  providers: Record<string, ProviderInfo>;
}

export function useModels() {
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/models")
      .then((r) => (r.ok ? r.json() : null))
      .then((data: ModelCatalog | null) => {
        if (!cancelled && data) {
          setCatalog(data);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  const providerOptions: ModelOption[] = catalog
    ? Object.keys(catalog.providers).map((p) => ({ label: p, value: p }))
    : [];

  const getModelOptions = (provider: string, mode: "deep" | "quick"): ModelOption[] => {
    if (!catalog) return [];
    const info = catalog.providers[provider];
    if (!info) return [];
    return info[mode];
  };

  const isCustomProvider = (provider: string): boolean => {
    if (!catalog) return false;
    return catalog.providers[provider]?.custom ?? false;
  };

  return { catalog, loading, providerOptions, getModelOptions, isCustomProvider };
}
