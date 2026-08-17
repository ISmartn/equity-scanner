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
import type { DarvasBoxDirection } from "@/lib/darvasBox";

export type BoxVariant = "darvas" | "greenStreak";

export interface DrawDarvasBox {
  startTime: Time;
  endTime: Time;
  top: number;
  bottom: number;
  direction: DarvasBoxDirection;
  variant?: BoxVariant;
}

class DarvasBoxRenderer implements ISeriesPrimitivePaneRenderer {
  constructor(
    private getBoxes: () => DrawDarvasBox[],
    private getSeries: () => ISeriesApi<"Candlestick"> | null,
    private getChart: () => IChartApiBase<Time> | null,
  ) {}

  draw(target: CanvasRenderingTarget2D) {
    this.paintBoxes(target);
  }

  drawBackground(target: CanvasRenderingTarget2D) {
    this.paintBoxes(target);
  }

  private paintBoxes(target: CanvasRenderingTarget2D) {
    const series = this.getSeries();
    const chart = this.getChart();
    if (!series || !chart) return;

    const boxes = this.getBoxes();
    if (!boxes.length) return;

    const timeScale = chart.timeScale();

    target.useBitmapCoordinateSpace(({ context, horizontalPixelRatio, verticalPixelRatio }) => {
      for (const box of boxes) {
        const x1 = timeScale.timeToCoordinate(box.startTime);
        const x2 = timeScale.timeToCoordinate(box.endTime);
        const yTop = series.priceToCoordinate(box.top);
        const yBottom = series.priceToCoordinate(box.bottom);

        if (x1 === null || x2 === null || yTop === null || yBottom === null) continue;

        const barWidth = Math.max(Math.abs(x2 - x1), 6);
        const centerX = ((x1 + x2) / 2) * horizontalPixelRatio;
        const width = barWidth * horizontalPixelRatio;
        const left = centerX - width / 2;
        const topY = Math.min(yTop, yBottom) * verticalPixelRatio;
        const height = Math.max(Math.abs(yBottom - yTop) * verticalPixelRatio, 2);

        const isUp = box.direction === "up";
        const variant = box.variant ?? "darvas";
        if (variant === "greenStreak") {
          context.fillStyle = "rgba(132, 204, 22, 0.2)";
          context.strokeStyle = "rgba(163, 230, 53, 0.95)";
        } else {
          context.fillStyle = isUp ? "rgba(34, 197, 94, 0.22)" : "rgba(239, 68, 68, 0.22)";
          context.strokeStyle = isUp ? "rgba(34, 197, 94, 0.85)" : "rgba(239, 68, 68, 0.85)";
        }
        context.lineWidth = Math.max(2, horizontalPixelRatio);
        context.fillRect(left, topY, width, height);
        context.strokeRect(left, topY, width, height);
      }
    });
  }
}

class DarvasBoxPaneView implements ISeriesPrimitivePaneView {
  constructor(private boxRenderer: DarvasBoxRenderer) {}

  zOrder() {
    return "bottom" as const;
  }

  renderer() {
    return this.boxRenderer;
  }
}

export class DarvasBoxPrimitive implements ISeriesPrimitive<Time> {
  private series: ISeriesApi<"Candlestick"> | null = null;
  private chart: IChartApiBase<Time> | null = null;
  private requestUpdate: (() => void) | null = null;
  private boxes: DrawDarvasBox[] = [];
  private readonly renderer: DarvasBoxRenderer;
  private readonly paneView: DarvasBoxPaneView;

  constructor() {
    this.renderer = new DarvasBoxRenderer(
      () => this.boxes,
      () => this.series,
      () => this.chart,
    );
    this.paneView = new DarvasBoxPaneView(this.renderer);
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

  setBoxes(boxes: DrawDarvasBox[]) {
    this.boxes = boxes;
    this.requestUpdate?.();
  }
}
