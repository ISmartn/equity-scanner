import type { CanvasRenderingTarget2D } from "fancy-canvas";
import type {
  IChartApiBase,
  ISeriesApi,
  ISeriesPrimitive,
  ISeriesPrimitivePaneRenderer,
  ISeriesPrimitivePaneView,
  SeriesAttachedParameter,
  Time,
} from "lightweight-charts";
import type { VcpOverlayData } from "@/lib/vcpOverlay";

const BAND_STYLE: Record<
  20 | 10 | 5,
  { fill: string; stroke: string }
> = {
  20: { fill: "rgba(56, 189, 248, 0.08)", stroke: "rgba(56, 189, 248, 0.45)" },
  10: { fill: "rgba(251, 191, 36, 0.1)", stroke: "rgba(251, 191, 36, 0.55)" },
  5: { fill: "rgba(245, 158, 11, 0.14)", stroke: "rgba(245, 158, 11, 0.75)" },
};

class VcpOverlayRenderer implements ISeriesPrimitivePaneRenderer {
  constructor(
    private getOverlay: () => VcpOverlayData | null,
    private getSeries: () => ISeriesApi<"Candlestick"> | null,
    private getChart: () => IChartApiBase<Time> | null,
  ) {}

  draw(target: CanvasRenderingTarget2D) {
    this.paint(target);
  }

  drawBackground(target: CanvasRenderingTarget2D) {
    this.paint(target);
  }

  private paint(target: CanvasRenderingTarget2D) {
    const overlay = this.getOverlay();
    const series = this.getSeries();
    const chart = this.getChart();
    if (!overlay || !series || !chart) return;

    const timeScale = chart.timeScale();

    target.useBitmapCoordinateSpace(({ context, horizontalPixelRatio, verticalPixelRatio }) => {
      const baseX1 = timeScale.timeToCoordinate(overlay.baseStartDate as Time);
      const baseX2 = timeScale.timeToCoordinate(overlay.baseEndDate as Time);
      const baseYTop = series.priceToCoordinate(overlay.baseTop);
      const baseYBottom = series.priceToCoordinate(overlay.baseBottom);
      if (baseX1 !== null && baseX2 !== null && baseYTop !== null && baseYBottom !== null) {
        const left = Math.min(baseX1, baseX2) * horizontalPixelRatio;
        const width = Math.max(Math.abs(baseX2 - baseX1), 8) * horizontalPixelRatio;
        const topY = Math.min(baseYTop, baseYBottom) * verticalPixelRatio;
        const height = Math.max(Math.abs(baseYBottom - baseYTop) * verticalPixelRatio, 2);
        context.fillStyle = "rgba(167, 139, 250, 0.06)";
        context.strokeStyle = "rgba(167, 139, 250, 0.35)";
        context.lineWidth = Math.max(1, horizontalPixelRatio);
        context.setLineDash([4 * horizontalPixelRatio, 4 * horizontalPixelRatio]);
        context.fillRect(left, topY, width, height);
        context.strokeRect(left, topY, width, height);
        context.setLineDash([]);
      }

      for (const band of overlay.bands) {
        const x1 = timeScale.timeToCoordinate(band.startDate as Time);
        const x2 = timeScale.timeToCoordinate(band.endDate as Time);
        const yTop = series.priceToCoordinate(band.top);
        const yBottom = series.priceToCoordinate(band.bottom);
        if (x1 === null || x2 === null || yTop === null || yBottom === null) continue;

        const style = BAND_STYLE[band.rangeDays];
        const left = Math.min(x1, x2) * horizontalPixelRatio;
        const width = Math.max(Math.abs(x2 - x1), 6) * horizontalPixelRatio;
        const topY = Math.min(yTop, yBottom) * verticalPixelRatio;
        const height = Math.max(Math.abs(yBottom - yTop) * verticalPixelRatio, 2);

        context.fillStyle = style.fill;
        context.strokeStyle = style.stroke;
        context.lineWidth = Math.max(band.rangeDays === 5 ? 2 : 1, horizontalPixelRatio);
        context.fillRect(left, topY, width, height);
        context.strokeRect(left, topY, width, height);
      }

      const pivotY = series.priceToCoordinate(overlay.pivotHigh);
      const pivotX1 = timeScale.timeToCoordinate(overlay.pivotStartDate as Time);
      const pivotX2 = timeScale.timeToCoordinate(overlay.asOfDate as Time);
      if (pivotY !== null && pivotX1 !== null && pivotX2 !== null) {
        const y = pivotY * verticalPixelRatio;
        const xStart = Math.min(pivotX1, pivotX2) * horizontalPixelRatio;
        const xEnd = Math.max(pivotX1, pivotX2) * horizontalPixelRatio;
        context.strokeStyle = overlay.breakout
          ? "rgba(52, 211, 153, 0.95)"
          : "rgba(251, 191, 36, 0.9)";
        context.lineWidth = Math.max(2, horizontalPixelRatio);
        context.setLineDash([6 * horizontalPixelRatio, 4 * horizontalPixelRatio]);
        context.beginPath();
        context.moveTo(xStart, y);
        context.lineTo(xEnd, y);
        context.stroke();
        context.setLineDash([]);
      }
    });
  }
}

class VcpOverlayPaneView implements ISeriesPrimitivePaneView {
  constructor(private overlayRenderer: VcpOverlayRenderer) {}

  zOrder() {
    return "bottom" as const;
  }

  renderer() {
    return this.overlayRenderer;
  }
}

export class VcpOverlayPrimitive implements ISeriesPrimitive<Time> {
  private series: ISeriesApi<"Candlestick"> | null = null;
  private chart: IChartApiBase<Time> | null = null;
  private requestUpdate: (() => void) | null = null;
  private overlay: VcpOverlayData | null = null;
  private readonly renderer: VcpOverlayRenderer;
  private readonly paneView: VcpOverlayPaneView;

  constructor() {
    this.renderer = new VcpOverlayRenderer(
      () => this.overlay,
      () => this.series,
      () => this.chart,
    );
    this.paneView = new VcpOverlayPaneView(this.renderer);
  }

  paneViews() {
    return [this.paneView];
  }

  updateAllViews() {}

  attached(param: SeriesAttachedParameter<Time, "Candlestick">) {
    this.series = param.series;
    this.chart = param.chart;
    this.requestUpdate = param.requestUpdate;
    this.requestUpdate?.();
  }

  detached() {
    this.series = null;
    this.chart = null;
    this.requestUpdate = null;
  }

  setOverlay(overlay: VcpOverlayData | null) {
    this.overlay = overlay;
    this.requestUpdate?.();
  }
}
