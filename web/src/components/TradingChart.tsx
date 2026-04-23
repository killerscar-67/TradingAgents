import { useEffect, useRef } from "react";
import styles from "./TradingChart.module.css";

export interface OhlcBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export interface PriceLine {
  price: number;
  color: string;
  label?: string;
}

export interface ChartMarker {
  time: number;
  position: "aboveBar" | "belowBar";
  shape: "arrowDown" | "arrowUp";
  text?: string;
}

interface Props {
  bars?: OhlcBar[];
  priceLines?: PriceLine[];
  markers?: ChartMarker[];
  height?: number;
  loading?: boolean;
}

export function TradingChart({
  bars,
  priceLines,
  markers,
  height = 300,
  loading = false,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const chartRef = useRef<any>(null);

  useEffect(() => {
    if (!containerRef.current || !bars || bars.length === 0) return;

    let chart: ReturnType<typeof import("lightweight-charts")["createChart"]> | undefined;

    import("lightweight-charts").then(({ createChart, ColorType }) => {
      if (!containerRef.current) return;

      chart = createChart(containerRef.current, {
        width: containerRef.current.clientWidth,
        height,
        layout: {
          background: { type: ColorType.Solid, color: "#0f1117" },
          textColor: "#94a3b8",
        },
        grid: {
          vertLines: { color: "#1e293b" },
          horzLines: { color: "#1e293b" },
        },
        timeScale: {
          borderColor: "#334155",
        },
        rightPriceScale: {
          borderColor: "#334155",
        },
      });
      chartRef.current = chart;

      const series = chart.addCandlestickSeries({
        upColor: "#4ade80",
        downColor: "#f87171",
        borderUpColor: "#4ade80",
        borderDownColor: "#f87171",
        wickUpColor: "#4ade80",
        wickDownColor: "#f87171",
      });

      // lightweight-charts expects time as UTCTimestamp (seconds) or string
      series.setData(
        bars.map((b) => ({
          time: b.time as unknown as import("lightweight-charts").UTCTimestamp,
          open: b.open,
          high: b.high,
          low: b.low,
          close: b.close,
        }))
      );

      if (priceLines) {
        for (const pl of priceLines) {
          series.createPriceLine({
            price: pl.price,
            color: pl.color,
            lineWidth: 1,
            lineStyle: 2,
            title: pl.label ?? "",
          });
        }
      }

      if (markers) {
        series.setMarkers(
          markers.map((m) => ({
            time: m.time as unknown as import("lightweight-charts").UTCTimestamp,
            position: m.position,
            shape: m.shape,
            color: m.shape === "arrowUp" ? "#4ade80" : "#f87171",
            text: m.text ?? "",
          }))
        );
      }

      chart.timeScale().fitContent();
    });

    return () => {
      chart?.remove();
      chartRef.current = null;
    };
  }, [bars, priceLines, markers, height]);

  if (loading) {
    return (
      <div className={styles.placeholder} style={{ height }}>
        <span className={styles.placeholderText}>Loading chart…</span>
      </div>
    );
  }

  if (!bars || bars.length === 0) {
    return (
      <div className={styles.placeholder} style={{ height }}>
        <span className={styles.placeholderText}>Chart will load when data is available</span>
      </div>
    );
  }

  return <div ref={containerRef} className={styles.chart} style={{ height }} />;
}
