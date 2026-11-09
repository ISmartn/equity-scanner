import { useCallback, useEffect, useRef, useState } from "react";
import { BrowserRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import Box from "@mui/material/Box";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Header } from "@/components/Header";
import { SettingsPanel } from "@/components/SettingsPanel";
import { fetchHealth } from "@/lib/api";
import { ForecastPage } from "@/pages/ForecastPage";
import { MoveFilterPage } from "@/pages/MoveFilterPage";
import { MarketInfoPage } from "@/pages/MarketInfoPage";
import { MomentumScannerPage } from "@/pages/MomentumScannerPage";
import { LiveScanPage } from "@/pages/LiveScanPage";
import { DarvasScreenerPage } from "@/pages/DarvasScreenerPage";
import { MultiYearBreakoutPage } from "@/pages/MultiYearBreakoutPage";
import { NewsImpactPage } from "@/pages/NewsImpactPage";
import { OiMomentumPage } from "@/pages/OiMomentumPage";
import { MtfRsiPage } from "@/pages/MtfRsiPage";
import { NiftyChartPage } from "@/pages/NiftyChartPage";
import { IndicatorAnalysisPage } from "@/pages/IndicatorAnalysisPage";
import { SectorRotationPage } from "@/pages/SectorRotationPage";
import { ElliottWaveLabPage } from "@/pages/experimental-labs/ElliottWave/ElliottWaveLabPage";
import { GrimesLabPage } from "@/pages/experimental-labs/Grimes/GrimesLabPage";
import { TimelineMoversPage } from "@/pages/TimelineMoversPage";
import { StockResearchPage } from "@/pages/StockResearchPage";

const NAV_TABS = [
  { label: "Forecast", path: "/" },
  { label: "Daily Move Filter", path: "/move-filter" },
  { label: "Timeline Movers", path: "/timeline" },
  { label: "Stock Research", path: "/stock-research" },
  { label: "News Impact", path: "/news-impact" },
  { label: "Market Info", path: "/market-info" },
  { label: "OI Momentum", path: "/oi-momentum" },
  { label: "MTF RSI", path: "/mtf-rsi" },
  { label: "Nifty Chart", path: "/nifty" },
  { label: "Indicator Analysis", path: "/indicator-analysis" },
  { label: "Momentum Scanner", path: "/scanner" },
  { label: "Live Scan", path: "/live-scan" },
  { label: "Darvas", path: "/darvas-screener" },
  { label: "Screener", path: "/multi-year-breakout" },
  { label: "Sector Rotation", path: "/sector-rotation" },
  { label: "EW Lab", path: "/experimental/elliott-wave-lab" },
  { label: "Grimes TA", path: "/grimes-analysis" },
] as const;

function AppNav() {
  const location = useLocation();
  const navigate = useNavigate();
  const scrollRef = useRef<HTMLElement>(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);
  const activeIndex = NAV_TABS.findIndex((tab) =>
    tab.path === "/"
      ? location.pathname === "/"
      : location.pathname === tab.path || location.pathname.startsWith(`${tab.path}/`),
  );

  const syncScrollState = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const maxScroll = el.scrollWidth - el.clientWidth;
    setCanScrollLeft(el.scrollLeft > 1);
    setCanScrollRight(el.scrollLeft < maxScroll - 1);
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    syncScrollState();
    const observer = new ResizeObserver(syncScrollState);
    observer.observe(el);
    return () => observer.disconnect();
  }, [syncScrollState]);

  useEffect(() => {
    scrollRef.current
      ?.querySelector('[data-nav-active="true"]')
      ?.scrollIntoView({ inline: "nearest", block: "nearest" });
  }, [activeIndex]);

  const scrollByStep = (direction: -1 | 1) => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollBy({ left: direction * Math.max(el.clientWidth * 0.6, 160), behavior: "smooth" });
  };

  return (
    <Box className="relative h-full">
      {canScrollLeft && (
        <>
          <div className="pointer-events-none absolute inset-y-0 left-0 z-10 w-10 bg-gradient-to-r from-surface to-transparent" />
          <button
            type="button"
            aria-label="Scroll tabs left"
            onClick={() => scrollByStep(-1)}
            className="absolute left-0 top-1/2 z-20 -translate-y-1/2 rounded-r border-y border-r border-surface-border bg-surface px-1 py-1.5 text-slate-400 transition hover:text-slate-100"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
          </button>
        </>
      )}
      {canScrollRight && (
        <>
          <div className="pointer-events-none absolute inset-y-0 right-0 z-10 w-10 bg-gradient-to-l from-surface to-transparent" />
          <button
            type="button"
            aria-label="Scroll tabs right"
            onClick={() => scrollByStep(1)}
            className="absolute right-0 top-1/2 z-20 -translate-y-1/2 rounded-l border-y border-l border-surface-border bg-surface px-1 py-1.5 text-slate-400 transition hover:text-slate-100"
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
        </>
      )}
      <nav
        ref={scrollRef}
        onScroll={syncScrollState}
        className="flex h-full items-stretch gap-0.5 overflow-x-auto px-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        aria-label="Primary"
      >
        {NAV_TABS.map((tab, index) => {
          const active = index === activeIndex;
          return (
            <button
              key={tab.path}
              type="button"
              data-nav-active={active}
              onClick={() => navigate(tab.path)}
              className={`shrink-0 whitespace-nowrap border-b-2 px-2 text-data-xs font-medium transition sm:px-2.5 sm:text-data-sm ${
                active
                  ? "border-accent font-semibold text-sky-300"
                  : "border-transparent text-slate-300 hover:border-surface-border hover:text-white"
              }`}
            >
              {tab.label}
            </button>
          );
        })}
      </nav>
    </Box>
  );
}

export default function App() {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [backendOnline, setBackendOnline] = useState(false);
  const [stocksWithData, setStocksWithData] = useState<number | null>(null);
  const [totalProfiles, setTotalProfiles] = useState<number | null>(null);

  useEffect(() => {
    const refresh = () => {
      fetchHealth().then((health) => {
        setBackendOnline(health?.status === "ok");
        if (health?.timeline) {
          setStocksWithData(health.timeline.symbols_with_data);
          setTotalProfiles(health.timeline.profile_count);
        }
      });
    };
    refresh();
    window.addEventListener("timeline-stats-updated", refresh);
    return () => window.removeEventListener("timeline-stats-updated", refresh);
  }, []);

  return (
    <BrowserRouter>
      <div className="min-h-screen">
        <Header
          onOpenSettings={() => setSettingsOpen(true)}
          backendOnline={backendOnline}
          stocksWithData={stocksWithData}
          totalProfiles={totalProfiles}
          nav={<AppNav />}
        />
        <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} />

        <Routes>
          <Route path="/" element={<ForecastPage />} />
          <Route path="/move-filter" element={<MoveFilterPage />} />
          <Route path="/timeline" element={<TimelineMoversPage />} />
          <Route path="/stock-research" element={<StockResearchPage />} />
          <Route path="/news-impact" element={<NewsImpactPage />} />
          <Route path="/market-info" element={<MarketInfoPage />} />
          <Route path="/oi-momentum" element={<OiMomentumPage />} />
          <Route path="/mtf-rsi" element={<MtfRsiPage />} />
          <Route path="/nifty" element={<NiftyChartPage />} />
          <Route path="/indicator-analysis" element={<IndicatorAnalysisPage />} />
          <Route path="/scanner" element={<MomentumScannerPage />} />
          <Route path="/live-scan" element={<LiveScanPage />} />
          <Route path="/darvas-screener" element={<DarvasScreenerPage />} />
          <Route path="/multi-year-breakout" element={<MultiYearBreakoutPage />} />
          <Route path="/sector-rotation" element={<SectorRotationPage />} />
          <Route path="/experimental/elliott-wave-lab" element={<ElliottWaveLabPage />} />
          <Route path="/grimes-analysis" element={<GrimesLabPage />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}
