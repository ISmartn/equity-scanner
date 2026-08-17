import { useEffect, useState } from "react";
import { BrowserRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import Box from "@mui/material/Box";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
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
import { TimelineMoversPage } from "@/pages/TimelineMoversPage";

const NAV_TABS = [
  { label: "Forecast", path: "/" },
  { label: "Daily Move Filter", path: "/move-filter" },
  { label: "Timeline Movers", path: "/timeline" },
  { label: "News Impact", path: "/news-impact" },
  { label: "Market Info", path: "/market-info" },
  { label: "OI Momentum", path: "/oi-momentum" },
  { label: "MTF RSI", path: "/mtf-rsi" },
  { label: "Momentum Scanner", path: "/scanner" },
  { label: "Screener", path: "/multi-year-breakout" },
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
      <Tabs
        value={activeIndex >= 0 ? activeIndex : false}
        onChange={(_, index) => navigate(NAV_TABS[index].path)}
        variant="scrollable"
        scrollButtons="auto"
        allowScrollButtonsMobile
        className="mx-auto max-w-7xl px-2 sm:px-4"
        sx={{
          minHeight: 48,
          "& .MuiTab-root": { minHeight: 48, px: 2 },
        }}
      >
        {NAV_TABS.map((tab) => (
          <Tab key={tab.path} label={tab.label} />
        ))}
      </Tabs>
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
          <Route path="/scanner" element={<MomentumScannerPage />} />
          <Route path="/multi-year-breakout" element={<MultiYearBreakoutPage />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}
