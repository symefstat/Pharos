import { lazy, Suspense, type ReactElement } from "react";
import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import { AppLayout } from "./components/layout";
import { ActionsProvider } from "./components/actions";
import { AuthProvider, useAuth } from "./lib/auth";

// Each page is a separate chunk, loaded on demand — the initial bundle no longer
// carries all 10 surfaces up front. React Router renders the matched route inside
// the Suspense boundary below while its chunk downloads.
const HomePage = lazy(() => import("./pages/Home"));
const BriefingPage = lazy(() => import("./pages/Briefing"));
const AskPage = lazy(() => import("./pages/Ask"));
const MotPage = lazy(() => import("./pages/Mot"));
const TechPage = lazy(() => import("./pages/Tech"));
const RadarPage = lazy(() => import("./pages/Radar"));
const AnalystReportPage = lazy(() => import("./pages/Analyst"));
const CapitalPage = lazy(() => import("./pages/Capital"));
const TrackRecordPage = lazy(() => import("./pages/TrackRecord"));
const ExplorePage = lazy(() => import("./pages/Explore"));
const ProsusPage = lazy(() => import("./pages/Prosus"));
const LoginPage = lazy(() => import("./pages/Login"));
const MethodologyPage = lazy(() => import("./pages/Methodology"));
const LegalPage = lazy(() => import("./pages/Legal"));

/** Shown briefly while a route's code chunk downloads. Pages render their own
 *  data skeletons once mounted, so this only covers the chunk fetch. */
function RouteFallback() {
  return (
    <div className="flex flex-1 items-center justify-center p-12 text-sm text-neutral-500">
      Loading…
    </div>
  );
}

/** Redirect to /login (remembering where we came from) unless signed in. */
function RequireAuth({ children }: { children: ReactElement }) {
  const { isAuthed } = useAuth();
  const location = useLocation();
  if (!isAuthed) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return children;
}

export default function App() {
  return (
    <AuthProvider>
      <ActionsProvider>
        <Suspense fallback={<RouteFallback />}>
          <Routes>
            <Route path="login" element={<LoginPage />} />
            <Route element={<AppLayout />}>
              {/* Home is the landing/navigation hub; the Briefing (previously
                  the index) lives at /briefing. */}
              <Route index element={<HomePage />} />
              <Route path="briefing" element={<BriefingPage />} />
              <Route path="ask" element={<AskPage />} />
              <Route
                path="prosus"
                element={
                  <RequireAuth>
                    <ProsusPage />
                  </RequireAuth>
                }
              />
              <Route path="mot" element={<MotPage />} />
              {/* Technology Dossier — one URL per tracked technology; the product
                  loop (signal → stage → forecast → outcome) on a single page. */}
              <Route path="tech/:key" element={<TechPage />} />
              <Route path="radar" element={<RadarPage />} />
              {/* Commissioned Analyst reports — permalink per report. */}
              <Route path="analyst/:id" element={<AnalystReportPage />} />
              <Route path="capital" element={<CapitalPage />} />
              {/* Forecasts + Ledger merged into one Track record page (2026-07-08).
                  It keeps the /ledger URL (in-app links + the public download point
                  there); /forecasts and /feeds redirect so bookmarks survive. */}
              <Route path="ledger" element={<TrackRecordPage />} />
              <Route path="forecasts" element={<Navigate to="/ledger" replace />} />
              <Route path="explore" element={<ExplorePage />} />
              <Route path="methodology" element={<MethodologyPage />} />
              <Route path="legal" element={<LegalPage />} />
              <Route path="feeds" element={<Navigate to="/explore?tab=stories" replace />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </Suspense>
      </ActionsProvider>
    </AuthProvider>
  );
}
