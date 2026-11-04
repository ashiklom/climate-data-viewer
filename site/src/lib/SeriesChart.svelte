<script lang="ts">
  // Interactive daily time series (Apache ECharts): mouse wheel zooms, drag pans, the slider below selects a
  // window, box zoom and reset are in the toolbox, hover shows every dataset's value. Clicking a day selects it.
  import { LineChart } from "echarts/charts";
  import { DataZoomComponent, GridComponent, LegendComponent, MarkLineComponent, ToolboxComponent, TooltipComponent } from "echarts/components";
  import * as echarts from "echarts/core";
  import { CanvasRenderer } from "echarts/renderers";
  import { onMount } from "svelte";

  import type { Series } from "./series";

  echarts.use([LineChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, ToolboxComponent, MarkLineComponent, CanvasRenderer]);

  let { series, labels, colors, yLabel, units, date, onpick }: {
    series: Series[];
    labels: Record<string, string>;
    colors: string[];
    yLabel: string;
    units: string;
    date: string;
    onpick?: (date: string) => void;
  } = $props();

  let el: HTMLDivElement;
  let chart: echarts.ECharts | undefined;
  const DAY = 86400000;
  const fmt = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? `${v.toFixed(2)} ${units}` : "—");

  function render() {
    if (!chart) return;
    chart.setOption({
      animation: false,
      useUTC: true, // days are UTC dates
      color: colors,
      grid: { left: 56, right: 24, top: 36, bottom: 64 },
      legend: { top: 0, type: "scroll", data: series.map((s) => labels[s.dataset] ?? s.dataset) },
      tooltip: {
        trigger: "axis",
        confine: true,
        axisPointer: { type: "line" },
        valueFormatter: fmt,
      },
      toolbox: { right: 8, top: 0, feature: { dataZoom: { yAxisIndex: "none", title: { zoom: "box zoom", back: "undo zoom" } }, restore: { title: "reset" } } },
      xAxis: { type: "time" },
      yAxis: { type: "value", scale: true, name: yLabel, nameLocation: "middle", nameGap: 40 },
      dataZoom: [
        { type: "inside", xAxisIndex: 0, filterMode: "weakFilter" },
        { type: "slider", xAxisIndex: 0, filterMode: "weakFilter", height: 18, bottom: 8 },
      ],
      series: series.map((s, i) => ({
        type: "line",
        name: labels[s.dataset] ?? s.dataset,
        showSymbol: false,
        lineStyle: { width: 1.2 },
        emphasis: { disabled: true },
        data: s.dates.map((d, j) => [Date.parse(d), Number.isFinite(s.values[j]) ? s.values[j] : null]),
        ...(i === 0 ? { markLine: { silent: true, symbol: "none", label: { show: false },
          lineStyle: { color: "#888", type: "dashed" }, data: [{ xAxis: Date.parse(date) }] } } : {}),
      })),
    }, { replaceMerge: ["series"] });
  }

  onMount(() => {
    chart = echarts.init(el);
    // click (not drag) anywhere in the plot area: select that day
    let down = [NaN, NaN];
    let hovered: number | undefined; // the day the tooltip snapped to
    chart.on("updateAxisPointer", (e) => { hovered = (e as { axesInfo: { value: number }[] }).axesInfo[0]?.value; });
    chart.getZr().on("mousedown", (e) => { down = [e.offsetX, e.offsetY]; });
    chart.getZr().on("click", (e) => {
      if (Math.hypot(e.offsetX - down[0]!, e.offsetY - down[1]!) > 3) return;
      if (!onpick || !chart?.containPixel("grid", [e.offsetX, e.offsetY])) return;
      const t = hovered ?? (chart.convertFromPixel({ gridIndex: 0 }, [e.offsetX, e.offsetY])[0] as number);
      onpick(new Date(Math.round(t / DAY) * DAY).toISOString().slice(0, 10));
    });
    const ro = new ResizeObserver(() => chart?.resize());
    ro.observe(el);
    render();
    return () => { ro.disconnect(); chart?.dispose(); };
  });

  $effect(() => {
    void [series, date, yLabel];
    render();
  });
</script>

<div class="chart" bind:this={el}></div>

<style>
  .chart { width: 100%; height: 100%; }
</style>
