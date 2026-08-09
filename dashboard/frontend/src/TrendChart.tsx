import { LineChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from "echarts/components";
import { init, use } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";
import { useI18n } from "./i18n";

use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

interface TrendChartProps {
  data: Array<{ date: string; pass: number; fail: number }>;
}

export function TrendChart({ data }: TrendChartProps) {
  const { language, t, formatNumber } = useI18n();
  const elementRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!elementRef.current) return;
    const chart = init(elementRef.current);
    const styles = getComputedStyle(document.documentElement);
    const foreground = styles.getPropertyValue("--ink").trim();
    const muted = styles.getPropertyValue("--ink-muted").trim();
    const border = styles.getPropertyValue("--line").trim();
    const success = styles.getPropertyValue("--success").trim();
    const danger = styles.getPropertyValue("--danger").trim();

    chart.setOption({
      animationDuration: 320,
      color: [success, danger],
      tooltip: {
        trigger: "axis",
        valueFormatter: (value: unknown) =>
          `${formatNumber(Number(value))} ${t("Nachrichten")}`,
      },
      legend: {
        data: [t("DMARC bestanden"), t("DMARC fehlgeschlagen")],
        bottom: 0,
        textStyle: { color: muted },
        icon: "circle",
      },
      grid: { left: 12, right: 14, top: 20, bottom: 46, containLabel: true },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: data.map((item) => item.date),
        axisLine: { lineStyle: { color: border } },
        axisTick: { show: false },
        axisLabel: {
          color: muted,
          formatter: (value: string) =>
            new Intl.DateTimeFormat(language === "de" ? "de-CH" : "en-GB", {
              day: "2-digit",
              month: "2-digit",
            }).format(new Date(`${value}T00:00:00Z`)),
        },
      },
      yAxis: {
        type: "value",
        minInterval: 1,
        axisLabel: { color: muted },
        splitLine: { lineStyle: { color: border } },
      },
      series: [
        {
          name: t("DMARC bestanden"),
          type: "line",
          smooth: 0.28,
          showSymbol: data.length < 14,
          symbolSize: 6,
          lineStyle: { width: 2 },
          areaStyle: { opacity: 0.08 },
          data: data.map((item) => item.pass),
        },
        {
          name: t("DMARC fehlgeschlagen"),
          type: "line",
          smooth: 0.28,
          showSymbol: data.length < 14,
          symbolSize: 6,
          lineStyle: { width: 2 },
          data: data.map((item) => item.fail),
        },
      ],
      textStyle: { color: foreground, fontFamily: "Inter, system-ui, sans-serif" },
    });

    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(elementRef.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [data, formatNumber, language, t]);

  return (
    <div
      className="trend-chart"
      ref={elementRef}
      role="img"
      aria-label={t(
        "Zeitverlauf der bestandenen und fehlgeschlagenen DMARC-Nachrichten",
      )}
    />
  );
}
