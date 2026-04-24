import "@testing-library/jest-dom";

// jsdom doesn't implement EventSource — provide a no-op stub for all tests.
class MockEventSource {
  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(url: string) { this.url = url; }
  close() {}
}
// eslint-disable-next-line @typescript-eslint/no-explicit-any
(globalThis as any).EventSource = MockEventSource;

if (!globalThis.matchMedia) {
  Object.defineProperty(globalThis, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

if (globalThis.HTMLCanvasElement) {
  const canvasContext = new Proxy({
    canvas: {},
    measureText: (text: string) => ({ width: text.length * 6 }),
    createLinearGradient: () => ({ addColorStop: () => {} }),
  }, {
    get(target, prop) {
      if (prop in target) return target[prop as keyof typeof target];
      return () => {};
    },
    set() {
      return true;
    },
  });

  Object.defineProperty(globalThis.HTMLCanvasElement.prototype, "getContext", {
    configurable: true,
    value: () => canvasContext,
  });
}
