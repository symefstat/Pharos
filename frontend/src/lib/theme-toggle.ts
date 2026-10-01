/**
 * Dark-mode preference — activation of the existing dark token block in
 * index.css (`:root[data-theme="dark"]`), nothing more.
 *
 * Three preferences, one resolved theme:
 *   - "light" / "dark"  — explicit override, persisted in localStorage;
 *   - "system"          — no stored override; follow prefers-color-scheme,
 *                         live (an OS theme change re-resolves immediately).
 *
 * The RESOLVED theme is always stamped on <html data-theme="light|dark">, so
 * the CSS never needs a duplicated @media token block — JS is the only place
 * that reads the media query. `initTheme()` runs synchronously at the top of
 * main.tsx, before React renders anything, so the first paint is already in
 * the right theme (no flash).
 */

export type ThemePref = "light" | "dark" | "system";

const STORAGE_KEY = "lodestar-theme";
const ORDER: ThemePref[] = ["light", "dark", "system"];

const media = () => window.matchMedia("(prefers-color-scheme: dark)");

/** The stored preference; anything absent/unknown means "system". */
export function getThemePref(): ThemePref {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw === "light" || raw === "dark" ? raw : "system";
  } catch {
    return "system";
  }
}

function resolve(pref: ThemePref): "light" | "dark" {
  if (pref === "system") return media().matches ? "dark" : "light";
  return pref;
}

function apply(pref: ThemePref) {
  document.documentElement.setAttribute("data-theme", resolve(pref));
}

/** Persist a preference ("system" = remove the override) and apply it. */
export function setThemePref(pref: ThemePref) {
  try {
    if (pref === "system") localStorage.removeItem(STORAGE_KEY);
    else localStorage.setItem(STORAGE_KEY, pref);
  } catch {
    /* private mode etc. — still apply for this page load */
  }
  apply(pref);
}

/** The next preference in the light → dark → system cycle. */
export function nextThemePref(pref: ThemePref): ThemePref {
  return ORDER[(ORDER.indexOf(pref) + 1) % ORDER.length];
}

/** Apply the stored preference before first paint and track OS changes. */
export function initTheme() {
  apply(getThemePref());
  media().addEventListener("change", () => {
    if (getThemePref() === "system") apply("system");
  });
}
