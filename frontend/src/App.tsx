import { useEffect, useState } from "react";
import { BrowserRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import Box from "@mui/material/Box";
import { Header } from "@/components/Header";
import { SettingsPanel } from "@/components/SettingsPanel";
import { fetchHealth } from "@/lib/api";
import { ForecastPage } from "@/pages/ForecastPage";
import { MoveFilterPage } from "@/pages/MoveFilterPage";
import { MarketInfoPage } from "@/pages/MarketInfoPage";
import { MomentumScannerPage } from "@/pages/MomentumScannerPage";
import { MultiYearBreakoutPage } from "@/pages/MultiYearBreakoutPage";
import { NewsImpactPage } from "@/pages/NewsImpactPage";
import { OiMomentumPage } from "@/pages/OiMomentumPage";
import { MtfRsiPage } from "@/pages/MtfRsiPage";
import { NiftyChartPage } from "@/pages/NiftyChartPage";
import { IndicatorAnalysisPage } from "@/pages/IndicatorAnalysisPage";
import { SectorRotationPage } from "@/pages/SectorRotationPage";
import { TimelineMoversPage } from "@/pages/TimelineMoversPage";

const NAV_TABS = [
  { label: "Forecast", path: "/" },
  { label: "Daily Move Filter", path: "/move-filter" },
  { label: "Timeline Movers", path: "/timeline" },
  { label: "News Impact", path: "/news-impact" },
  { label: "Market Info", path: "/market-info" },
  { label: "OI Momentum", path: "/oi-momentum" },
  { label: "MTF RSI", path: "/mtf-rsi" },
  { label: "Nifty Chart", path: "/nifty" },
  { label: "Indicator Analysis", path: "/indicator-analysis" },
  { label: "Momentum Scanner", path: "/scanner" },
  { label: "Screener", path: "/multi-year-breakout" },
  { label: "Sector Rotation", path: "/sector-rotation" },
] as const;

function AppNav() {
  const location = useLocation();
  const navigate = useNavigate();
  const activeIndex = NAV_TABS.findIndex((tab) =>
    tab.path === "/"
      ? location.pathname === "/"
      : location.pathname === tab.path || location.pathname.startsWith(`${tab.path}/`),
  );

  return (
    <Box className="border-b border-surface-border bg-surface/50">
      <nav
        className="mx-auto flex max-w-[1920px] items-stretch gap-0.5 overflow-x-auto px-2 sm:px-4 [scrollbar-width:thin] [&::-webkit-scrollbar]:h-1.5"
        aria-label="Primary"
      >
        {NAV_TABS.map((tab, index) => {
          const active = index === activeIndex;
          return (
            <button
              key={tab.path}
              type="button"
              onClick={() => navigate(tab.path)}
              className={`shrink-0 whitespace-nowrap border-b-2 px-2 py-2 text-[11px] font-medium transition sm:px-2.5 sm:text-xs ${
                active
                  ? "border-accent text-accent"
                  : "border-transparent text-slate-400 hover:border-surface-border hover:text-slate-200"
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
        />
        <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} />
        <AppNav />

        <Routes>
          <Route path="/" element={<ForecastPage />} />
          <Route path="/move-filter" element={<MoveFilterPage />} />
          <Route path="/timeline" element={<TimelineMoversPage />} />
          <Route path="/news-impact" element={<NewsImpactPage />} />
          <Route path="/market-info" element={<MarketInfoPage />} />
          <Route path="/oi-momentum" element={<OiMomentumPage />} />
          <Route path="/mtf-rsi" element={<MtfRsiPage />} />
          <Route path="/nifty" element={<NiftyChartPage />} />
          <Route path="/indicator-analysis" element={<IndicatorAnalysisPage />} />
          <Route path="/scanner" element={<MomentumScannerPage />} />
          <Route path="/multi-year-breakout" element={<MultiYearBreakoutPage />} />
          <Route path="/sector-rotation" element={<SectorRotationPage />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}
