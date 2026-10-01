import { useEffect, useState, type ReactNode } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  BookCheck,
  BookOpen,
  Briefcase,
  Compass,
  House,
  MessageSquare,
  FlaskConical,
  Monitor,
  Moon,
  Sun,
  Wallet,
  Search,
  RefreshCw,
  LogIn,
  LogOut,
  Menu,
  Radar,
} from "lucide-react";
import { cn } from "../lib/utils";
import { useAuth } from "../lib/auth";
import {
  getThemePref,
  nextThemePref,
  setThemePref,
  type ThemePref,
} from "../lib/theme-toggle";

interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
  end?: boolean;
  /** Only shown to a signed-in admin (sensitive data). */
  adminOnly?: boolean;
  /** Extra path prefix that keeps this item highlighted (e.g. /tech/* dossier
   *  pages belong to Technologies). */
  alsoMatch?: string;
}

/** Cycles light → dark → system. "System" removes the override and follows the
 *  OS preference (lib/theme-toggle.ts owns persistence + the pre-paint stamp). */
function ThemeToggle() {
  const [pref, setPref] = useState<ThemePref>(getThemePref);
  const icons: Record<ThemePref, ReactNode> = {
    light: <Sun className="h-3.5 w-3.5" />,
    dark: <Moon className="h-3.5 w-3.5" />,
    system: <Monitor className="h-3.5 w-3.5" />,
  };
  const next = nextThemePref(pref);
  return (
    <button
      onClick={() => {
        setThemePref(next);
        setPref(next);
      }}
      title={`Theme: ${pref} — click for ${next}`}
      aria-label={`Theme: ${pref}. Switch to ${next}.`}
      className="rounded-md p-1.5 text-white/40 transition-colors hover:bg-white/8 hover:text-white/80"
    >
      {icons[pref]}
    </button>
  );
}

/* Ordered as the guided workflow reads: the daily entry point (Briefing), the
   intelligence layer (Technologies), the trust engine (Track record), the
   capital view, then the support tools (Ask) and the evidence base (Explore). */
const NAV: NavItem[] = [
  { to: "/", label: "Home", icon: <House className="h-[17px] w-[17px]" />, end: true },
  { to: "/briefing", label: "Briefing", icon: <Compass className="h-[17px] w-[17px]" /> },
  { to: "/mot", label: "Technologies", icon: <FlaskConical className="h-[17px] w-[17px]" />, alsoMatch: "/tech" },
  { to: "/radar", label: "Radar", icon: <Radar className="h-[17px] w-[17px]" /> },
  { to: "/ledger", label: "Track record", icon: <BookCheck className="h-[17px] w-[17px]" /> },
  { to: "/capital", label: "Capital", icon: <Wallet className="h-[17px] w-[17px]" /> },
  { to: "/ask", label: "Ask", icon: <MessageSquare className="h-[17px] w-[17px]" /> },
  { to: "/prosus", label: "Prosus", icon: <Briefcase className="h-[17px] w-[17px]" />, adminOnly: true },
  { to: "/explore", label: "Explore", icon: <Search className="h-[17px] w-[17px]" /> },
  { to: "/methodology", label: "Methodology", icon: <BookOpen className="h-[17px] w-[17px]" /> },
];

export function Sidebar({ onNavigate }: { onNavigate?: () => void } = {}) {
  const { isAuthed, logout } = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const items = NAV.filter((item) => !item.adminOnly || isAuthed);
  return (
    <aside className="sticky top-0 flex h-screen w-[232px] shrink-0 flex-col bg-gradient-to-b from-[#2b3f95] via-[#243786] to-[#192454] text-white">
      <div className="flex items-center gap-2.5 px-5 pb-6 pt-6">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-white/95 shadow-[0_2px_8px_rgba(0,0,0,0.18)]">
          <img src="/brand/pharos-symbol.png" alt="" className="h-[26px] w-[26px]" />
        </div>
        <div className="leading-tight">
          <div className="text-[14px] font-semibold uppercase tracking-[0.24em] text-white">Pharos</div>
          <div className="text-[11px] text-white/55">Strategic Intelligence</div>
        </div>
      </div>

      <div className="px-5 pb-2 text-[10.5px] font-medium uppercase tracking-[0.1em] text-white/40">
        Workspace
      </div>
      <nav className="flex-1 space-y-0.5 px-3">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-[13.5px] font-medium transition-colors",
                isActive || (item.alsoMatch && pathname.startsWith(item.alsoMatch))
                  ? "bg-white/15 text-white shadow-[inset_0_0_0_1px_rgba(255,255,255,0.08)]"
                  : "text-white/65 hover:bg-white/8 hover:text-white",
              )
            }
          >
            {({ isActive }) => {
              const active = isActive || (item.alsoMatch && pathname.startsWith(item.alsoMatch));
              return (
                <>
                  <span className={active ? "text-[#a9c4ff]" : "text-white/55"}>{item.icon}</span>
                  <span>{item.label}</span>
                </>
              );
            }}
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-white/10 px-3 py-3">
        {isAuthed ? (
          <button
            onClick={() => {
              onNavigate?.();
              logout();
              navigate("/");
            }}
            className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-[13.5px] font-medium text-white/65 transition-colors hover:bg-white/8 hover:text-white"
          >
            <LogOut className="h-[17px] w-[17px] text-white/55" />
            <span>Log out</span>
          </button>
        ) : (
          <NavLink
            to="/login"
            onClick={onNavigate}
            className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-[13.5px] font-medium text-white/65 transition-colors hover:bg-white/8 hover:text-white"
          >
            <LogIn className="h-[17px] w-[17px] text-white/55" />
            <span>Admin login</span>
          </NavLink>
        )}
        <div className="mt-1 flex items-center justify-between pl-3 pr-1.5">
          <NavLink
            to="/legal"
            className="text-[11px] text-white/40 transition-colors hover:text-white/75"
          >
            Legal
          </NavLink>
          <ThemeToggle />
        </div>
      </div>
    </aside>
  );
}

export function AppLayout() {
  const [navOpen, setNavOpen] = useState(false);
  const { pathname } = useLocation();
  // a route change means the user navigated — the drawer's job is done
  useEffect(() => setNavOpen(false), [pathname]);
  return (
    <div className="flex min-h-screen">
      <div className="hidden md:block">
        <Sidebar />
      </div>
      <div className="flex min-w-0 flex-1 flex-col">
        {/* mobile top bar — the only chrome under 768px */}
        <div className="sticky top-0 z-30 flex items-center gap-3 border-b border-line bg-surface px-4 py-2.5 md:hidden">
          <button
            type="button"
            onClick={() => setNavOpen(true)}
            aria-label="Open navigation"
            className="flex h-9 w-9 items-center justify-center rounded-lg border border-line text-ink-soft"
          >
            <Menu className="h-4.5 w-4.5" />
          </button>
          <span className="flex h-7 w-7 items-center justify-center rounded-lg border border-line bg-white">
            <img src="/brand/pharos-symbol.png" alt="" className="h-[19px] w-[19px]" />
          </span>
          <span className="text-[13px] font-semibold uppercase tracking-[0.24em]">Pharos</span>
        </div>
        <Outlet />
      </div>
      {navOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div
            className="absolute inset-0 bg-black/45"
            onClick={() => setNavOpen(false)}
            aria-hidden="true"
          />
          <div className="absolute inset-y-0 left-0 shadow-2xl">
            <Sidebar onNavigate={() => setNavOpen(false)} />
          </div>
        </div>
      )}
    </div>
  );
}

export function Topbar({
  title,
  subtitle,
  live,
  updatedAt,
  loading,
  onRefresh,
  refreshLabel = "Refresh",
}: {
  title: string;
  subtitle?: string;
  live?: boolean;
  updatedAt: Date | null;
  loading: boolean;
  onRefresh: () => void;
  /** Override when the action isn't a data refresh (e.g. Ask's "New chat"). */
  refreshLabel?: string;
}) {
  return (
    <header className="sticky top-0 z-10 flex items-center justify-between border-b border-line bg-surface/85 px-8 py-4 backdrop-blur">
      <div>
        <h1 className="text-[18px] font-semibold leading-tight tracking-tight text-ink">{title}</h1>
        {subtitle && <p className="mt-0.5 text-[12.5px] text-muted">{subtitle}</p>}
      </div>
      <div className="flex items-center gap-5">
        {live && (
          <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-muted">
            <span className="h-1.5 w-1.5 rounded-full bg-up" />
            Live
          </span>
        )}
        {updatedAt && (
          <span className="hidden text-[12px] text-faint sm:inline">
            Updated{" "}
            {updatedAt.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
          </span>
        )}
        <button
          onClick={onRefresh}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-1.5 text-[13px] font-medium text-ink-soft transition-colors hover:border-line-strong hover:text-ink disabled:opacity-50"
        >
          <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
          {refreshLabel}
        </button>
      </div>
    </header>
  );
}
