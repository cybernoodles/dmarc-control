import {
  Activity,
  Bell,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Clock3,
  Database,
  EyeOff,
  FileSearch,
  Globe2,
  Info,
  LayoutDashboard,
  LockKeyhole,
  Palette,
  RefreshCw,
  Save,
  Search,
  Server,
  Settings2,
  ShieldCheck,
  TriangleAlert,
  X,
} from "lucide-react";
import {
  FormEvent,
  ReactNode,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useState,
} from "react";
import {
  Alert,
  AlertStatus,
  AppearanceSettings,
  DomainItem,
  Forensics,
  Host,
  Overview,
  TrustStatus,
  api,
} from "./api";
import { LanguageProvider, useI18n } from "./i18n";
import { TrendChart } from "./TrendChart";

type View = "overview" | "hosts" | "alerts" | "forensics" | "settings";

const DEFAULT_BRAND_COLOR = "#173f43";
const BRAND_STORAGE_KEY = "dmarc-control-brand-color";
const CUSTOM_BRAND_STORAGE_KEY = "dmarc-control-custom-brand-color";
const SETTINGS_TOKEN_SESSION_KEY = "dmarc-control-settings-token";

function classNames(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

function normalizeHex(value: string) {
  const normalized = value.trim().toLowerCase();
  return /^#[0-9a-f]{6}$/.test(normalized) ? normalized : null;
}

function hexToRgb(value: string) {
  const normalized = normalizeHex(value) ?? DEFAULT_BRAND_COLOR;
  return {
    r: Number.parseInt(normalized.slice(1, 3), 16),
    g: Number.parseInt(normalized.slice(3, 5), 16),
    b: Number.parseInt(normalized.slice(5, 7), 16),
  };
}

function rgbToHex(r: number, g: number, b: number) {
  const channel = (value: number) =>
    Math.min(255, Math.max(0, Math.round(value)))
      .toString(16)
      .padStart(2, "0");
  return `#${channel(r)}${channel(g)}${channel(b)}`;
}

function contrastColor(r: number, g: number, b: number) {
  const linear = [r, g, b].map((channel) => {
    const value = channel / 255;
    return value <= 0.03928
      ? value / 12.92
      : Math.pow((value + 0.055) / 1.055, 2.4);
  });
  const luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
  return luminance > 0.46 ? "#102326" : "#ffffff";
}

function blendColor(
  base: { r: number; g: number; b: number },
  brand: { r: number; g: number; b: number },
  brandWeight: number,
) {
  return rgbToHex(
    base.r * (1 - brandWeight) + brand.r * brandWeight,
    base.g * (1 - brandWeight) + brand.g * brandWeight,
    base.b * (1 - brandWeight) + brand.b * brandWeight,
  );
}

function applyBrandPalette(color: string | null, darkMode = false) {
  const root = document.documentElement;
  const properties = [
    "--primary",
    "--primary-soft",
    "--primary-hover",
    "--primary-contrast",
    "--brand-glow",
    "--focus-ring",
    "--canvas",
    "--surface",
    "--surface-soft",
    "--line",
    "--line-strong",
    "--neutral-track",
    "--shadow",
  ];
  if (!color) {
    properties.forEach((property) => root.style.removeProperty(property));
    return;
  }

  const normalized = normalizeHex(color);
  if (!normalized) return;
  const { r, g, b } = hexToRgb(normalized);
  root.style.setProperty("--primary", normalized);
  root.style.setProperty("--primary-soft", `rgba(${r}, ${g}, ${b}, 0.13)`);
  root.style.setProperty(
    "--primary-hover",
    rgbToHex(r * 0.8, g * 0.8, b * 0.8),
  );
  root.style.setProperty("--primary-contrast", contrastColor(r, g, b));
  root.style.setProperty("--brand-glow", `rgba(${r}, ${g}, ${b}, 0.09)`);
  root.style.setProperty("--focus-ring", `rgba(${r}, ${g}, ${b}, 0.25)`);

  const brand = { r, g, b };
  const surfaces = darkMode
    ? {
        canvas: blendColor({ r: 16, g: 23, b: 25 }, brand, 0.08),
        surface: blendColor({ r: 23, g: 33, b: 36 }, brand, 0.08),
        surfaceSoft: blendColor({ r: 28, g: 41, b: 45 }, brand, 0.12),
        line: blendColor({ r: 43, g: 58, b: 63 }, brand, 0.15),
        lineStrong: blendColor({ r: 59, g: 76, b: 81 }, brand, 0.18),
        neutralTrack: blendColor({ r: 41, g: 52, b: 56 }, brand, 0.1),
        shadow: `0 10px 34px rgba(${r}, ${g}, ${b}, 0.11)`,
      }
    : {
        canvas: blendColor({ r: 246, g: 248, b: 249 }, brand, 0.035),
        surface: blendColor({ r: 255, g: 255, b: 255 }, brand, 0.018),
        surfaceSoft: blendColor({ r: 250, g: 251, b: 252 }, brand, 0.045),
        line: blendColor({ r: 220, g: 228, b: 231 }, brand, 0.08),
        lineStrong: blendColor({ r: 203, g: 214, b: 218 }, brand, 0.12),
        neutralTrack: blendColor({ r: 237, g: 241, b: 242 }, brand, 0.08),
        shadow: `0 10px 34px rgba(${r}, ${g}, ${b}, 0.065)`,
      };

  root.style.setProperty("--canvas", surfaces.canvas);
  root.style.setProperty("--surface", surfaces.surface);
  root.style.setProperty("--surface-soft", surfaces.surfaceSoft);
  root.style.setProperty("--line", surfaces.line);
  root.style.setProperty("--line-strong", surfaces.lineStrong);
  root.style.setProperty("--neutral-track", surfaces.neutralTrack);
  root.style.setProperty("--shadow", surfaces.shadow);
}

function flagForCountry(country: string | null | undefined) {
  if (!country || !/^[A-Za-z]{2}$/.test(country)) return "🌐";
  return country
    .toUpperCase()
    .split("")
    .map((character) =>
      String.fromCodePoint(127397 + character.charCodeAt(0)),
    )
    .join("");
}

function IpWithFlag({
  ip,
  country,
}: {
  ip: string;
  country: string | null | undefined;
}) {
  const { t } = useI18n();
  const normalized = country?.toUpperCase();
  const label =
    normalized && /^[A-Z]{2}$/.test(normalized)
      ? t("Herkunftsland {country}", { country: normalized })
      : t("Herkunftsland unbekannt");
  return (
    <span className="ip-with-flag">
      <span className="country-flag" role="img" aria-label={label}>
        {flagForCountry(country)}
      </span>
      <span className="mono">{ip}</span>
    </span>
  );
}

function StatusPill({
  tone,
  children,
}: {
  tone: "critical" | "warning" | "success" | "info" | "neutral";
  children: ReactNode;
}) {
  return <span className={`status-pill status-${tone}`}>{children}</span>;
}

function LoadingState({ label }: { label?: string }) {
  const { t } = useI18n();
  return (
    <div className="state-box" role="status">
      <RefreshCw className="spin" aria-hidden="true" />
      <span>{label ?? t("Daten werden geladen")}</span>
    </div>
  );
}

function EmptyState({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="state-box state-empty">
      <CheckCircle2 aria-hidden="true" />
      <div>
        <strong>{title}</strong>
        <p>{description}</p>
      </div>
    </div>
  );
}

function ErrorState({ message, retry }: { message: string; retry: () => void }) {
  const { t } = useI18n();
  return (
    <div className="state-box state-error" role="alert">
      <CircleAlert aria-hidden="true" />
      <div>
        <strong>{t("Daten konnten nicht geladen werden")}</strong>
        <p>{message}</p>
      </div>
      <button className="button button-secondary" type="button" onClick={retry}>
        {t("Erneut versuchen")}
      </button>
    </div>
  );
}

function SectionHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <div className="section-head">
      <div>
        <h2>{title}</h2>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

function AlignmentBar({
  label,
  value,
  total,
  tone,
}: {
  label: string;
  value: number;
  total: number;
  tone: "success" | "danger" | "info" | "warning";
}) {
  const { formatNumber } = useI18n();
  const percentage = total ? Math.min(100, (value / total) * 100) : 0;
  return (
    <div className="alignment-row">
      <div>
        <span>{label}</span>
        <strong>
          {formatNumber(value)} / {formatNumber(total)}
        </strong>
      </div>
      <div
        className="bar-track"
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={value}
      >
        <span
          className={`bar-fill bar-${tone}`}
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
}

function TopList({
  items,
  empty,
}: {
  items: Array<{ name: string; value: number; meta?: string }>;
  empty: string;
}) {
  const { formatNumber } = useI18n();
  const maximum = Math.max(...items.map((item) => item.value), 1);
  if (!items.length) {
    return <p className="muted compact-empty">{empty}</p>;
  }
  return (
    <div className="top-list">
      {items.map((item) => (
        <div className="top-list-item" key={`${item.name}-${item.meta ?? ""}`}>
          <div>
            <span className="truncate">{item.name}</span>
            <strong>{formatNumber(item.value)}</strong>
          </div>
          <div className="mini-track" aria-hidden="true">
            <span style={{ width: `${(item.value / maximum) * 100}%` }} />
          </div>
          {item.meta && <small>{item.meta}</small>}
        </div>
      ))}
    </div>
  );
}

export function App() {
  return (
    <LanguageProvider>
      <DashboardApp />
    </LanguageProvider>
  );
}

function DashboardApp() {
  const { t } = useI18n();
  const [view, setView] = useState<View>("overview");
  const [domains, setDomains] = useState<DomainItem[]>([]);
  const [domain, setDomain] = useState("*");
  const [days, setDays] = useState(30);
  const [domainError, setDomainError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [brandColor, setBrandColorState] = useState(() => {
    try {
      return (
        normalizeHex(localStorage.getItem(BRAND_STORAGE_KEY) ?? "") ??
        DEFAULT_BRAND_COLOR
      );
    } catch {
      return DEFAULT_BRAND_COLOR;
    }
  });
  const [hasLocalBrand, setHasLocalBrand] = useState(() => {
    try {
      return Boolean(normalizeHex(localStorage.getItem(BRAND_STORAGE_KEY) ?? ""));
    } catch {
      return false;
    }
  });
  const [customColor, setCustomColor] = useState<string | null>(() => {
    try {
      return normalizeHex(localStorage.getItem(CUSTOM_BRAND_STORAGE_KEY) ?? "");
    } catch {
      return null;
    }
  });
  const [appearance, setAppearance] = useState<AppearanceSettings | null>(null);
  const [appearanceError, setAppearanceError] = useState("");

  useLayoutEffect(() => {
    const color =
      brandColor === DEFAULT_BRAND_COLOR ? null : brandColor;
    const colorScheme = window.matchMedia("(prefers-color-scheme: dark)");
    const applyPalette = () => applyBrandPalette(color, colorScheme.matches);
    applyPalette();
    colorScheme.addEventListener("change", applyPalette);
    return () => colorScheme.removeEventListener("change", applyPalette);
  }, [brandColor]);

  useEffect(() => {
    setAppearanceError("");
    api
      .appearance()
      .then((settings) => {
        setAppearance(settings);
        try {
          if (!normalizeHex(localStorage.getItem(BRAND_STORAGE_KEY) ?? "")) {
            setBrandColorState(settings.global_color);
          }
          if (
            settings.global_profile === "custom" &&
            !normalizeHex(
              localStorage.getItem(CUSTOM_BRAND_STORAGE_KEY) ?? "",
            )
          ) {
            setCustomColor(settings.global_color);
          }
        } catch {
          if (!hasLocalBrand) setBrandColorState(settings.global_color);
        }
      })
      .catch((error: Error) => setAppearanceError(error.message));
  }, []);

  const updateBrandColor = (color: string) => {
    const normalized = normalizeHex(color);
    if (!normalized) return;
    setBrandColorState(normalized);
    setHasLocalBrand(true);
    try {
      localStorage.setItem(BRAND_STORAGE_KEY, normalized);
    } catch {
      // The live preview still works if storage is unavailable.
    }
  };

  const saveCustomColor = () => {
    setCustomColor(brandColor);
    try {
      localStorage.setItem(CUSTOM_BRAND_STORAGE_KEY, brandColor);
    } catch {
      // The saved profile remains available for the current page.
    }
  };

  const resetLocalBrand = () => {
    setBrandColorState(appearance?.global_color ?? DEFAULT_BRAND_COLOR);
    setHasLocalBrand(false);
    try {
      localStorage.removeItem(BRAND_STORAGE_KEY);
    } catch {
      // Reset remains effective for the current page.
    }
  };

  const updateGlobalAppearance = async (
    profile: AppearanceSettings["global_profile"],
    color: string | null,
    settingsToken: string,
  ) => {
    const updated = await api.updateAppearance(profile, color, settingsToken);
    setAppearance(updated);
    setBrandColorState(updated.global_color);
    setHasLocalBrand(false);
    try {
      localStorage.removeItem(BRAND_STORAGE_KEY);
    } catch {
      // The global color still applies for the current page.
    }
    return updated;
  };

  const loadDomains = useCallback(() => {
    setDomainError("");
    api.domains().then(setDomains).catch((error: Error) => setDomainError(error.message));
  }, []);

  useEffect(() => {
    loadDomains();
  }, [loadDomains, refreshKey]);

  const scopeLabel = `${domain === "*" ? t("Alle Domains") : domain} · ${t(
    "{days} Tage",
    { days },
  )}`;

  const navigation: Array<{
    id: View;
    label: string;
    icon: typeof LayoutDashboard;
  }> = [
    { id: "overview", label: t("Übersicht"), icon: LayoutDashboard },
    { id: "hosts", label: "Sending Hosts", icon: Server },
    { id: "alerts", label: t("Warnungen"), icon: Bell },
    { id: "forensics", label: t("Forensik"), icon: FileSearch },
  ];

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark">
            <ShieldCheck aria-hidden="true" />
          </span>
          <div>
            <strong>DMARC Control</strong>
            <span>{t("Mail-Authentifizierungsbetrieb")}</span>
          </div>
        </div>
        <div className="health-label">
          <span className="health-dot" />
          {t("Live aus OpenSearch")}
        </div>
      </header>

      <nav className="main-nav" aria-label={t("Dashboard-Bereiche")}>
        {navigation.map((item) => {
          const Icon = item.icon;
          return (
            <button
              type="button"
              key={item.id}
              className={classNames("nav-button", view === item.id && "active")}
              aria-current={view === item.id ? "page" : undefined}
              onClick={() => setView(item.id)}
            >
              <Icon aria-hidden="true" />
              {item.label}
            </button>
          );
        })}
        <button
          type="button"
          className={classNames(
            "nav-button",
            "nav-settings-button",
            view === "settings" && "active",
          )}
          aria-current={view === "settings" ? "page" : undefined}
          onClick={() => setView("settings")}
        >
          <Settings2 aria-hidden="true" />
          {t("Einstellungen")}
        </button>
      </nav>

      {view !== "settings" && (
        <div className="scope-bar">
          <div className="filters">
            <label>
              <span>Domain</span>
              <select value={domain} onChange={(event) => setDomain(event.target.value)}>
                <option value="*">{t("Alle Domains")}</option>
                {domains.map((item) => (
                  <option value={item.domain} key={item.domain}>
                    {item.domain}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>{t("Zeitraum")}</span>
              <select
                value={days}
                onChange={(event) => setDays(Number(event.target.value))}
              >
                <option value={7}>{t("Letzte 7 Tage")}</option>
                <option value={30}>{t("Letzte 30 Tage")}</option>
                <option value={90}>{t("Letzte 90 Tage")}</option>
                <option value={365}>{t("Letzte 12 Monate")}</option>
              </select>
            </label>
          </div>
          <div className="scope-meta">
            <span>{scopeLabel}</span>
            <button
              className="icon-button"
              type="button"
              aria-label={t("Daten aktualisieren")}
              title={t("Daten aktualisieren")}
              onClick={() => setRefreshKey((value) => value + 1)}
            >
              <RefreshCw aria-hidden="true" />
            </button>
          </div>
        </div>
      )}

      {domainError && view !== "settings" && (
        <div className="inline-warning">
          <TriangleAlert aria-hidden="true" />
          {t("Domain-Liste nicht verfügbar: {error}", { error: domainError })}
        </div>
      )}

      <main>
        {view === "overview" && (
          <OverviewView
            domain={domain}
            days={days}
            refreshKey={refreshKey}
            openAlerts={() => setView("alerts")}
            openHosts={() => setView("hosts")}
          />
        )}
        {view === "hosts" && (
          <HostsView domain={domain} days={days} refreshKey={refreshKey} />
        )}
        {view === "alerts" && (
          <AlertsView domain={domain} days={days} refreshKey={refreshKey} />
        )}
        {view === "forensics" && (
          <ForensicsView domain={domain} days={days} refreshKey={refreshKey} />
        )}
        {view === "settings" && (
          <SettingsView
            color={brandColor}
            customColor={customColor}
            hasLocalBrand={hasLocalBrand}
            appearance={appearance}
            appearanceError={appearanceError}
            updateColor={updateBrandColor}
            saveCustomColor={saveCustomColor}
            resetLocalBrand={resetLocalBrand}
            updateGlobalAppearance={updateGlobalAppearance}
          />
        )}
      </main>

      <footer>
        <span>DMARC Control MVP</span>
        <span>
          {t(
            "OpenSearch ist ausschließlich über die kontrollierte API erreichbar.",
          )}
        </span>
      </footer>
    </div>
  );
}

function SettingsView({
  color,
  customColor,
  hasLocalBrand,
  appearance,
  appearanceError,
  updateColor,
  saveCustomColor,
  resetLocalBrand,
  updateGlobalAppearance,
}: {
  color: string;
  customColor: string | null;
  hasLocalBrand: boolean;
  appearance: AppearanceSettings | null;
  appearanceError: string;
  updateColor: (color: string) => void;
  saveCustomColor: () => void;
  resetLocalBrand: () => void;
  updateGlobalAppearance: (
    profile: AppearanceSettings["global_profile"],
    color: string | null,
    settingsToken: string,
  ) => Promise<AppearanceSettings>;
}) {
  const { language, setLanguage, t } = useI18n();
  const [settingsToken, setSettingsToken] = useState(() => {
    try {
      return sessionStorage.getItem(SETTINGS_TOKEN_SESSION_KEY) ?? "";
    } catch {
      return "";
    }
  });
  const [message, setMessage] = useState("");
  const [messageTone, setMessageTone] = useState<
    "success" | "critical" | "info"
  >("info");
  const [savingGlobal, setSavingGlobal] = useState(false);
  const rgb = hexToRgb(color);
  const customRgb = customColor ? hexToRgb(customColor) : null;
  const updateChannel = (channel: "r" | "g" | "b", value: string) => {
    const parsed = Number.parseInt(value, 10);
    const next = {
      ...rgb,
      [channel]: Number.isFinite(parsed)
        ? Math.min(255, Math.max(0, parsed))
        : 0,
    };
    updateColor(rgbToHex(next.r, next.g, next.b));
  };
  const updateToken = (value: string) => {
    setSettingsToken(value);
    try {
      if (value) {
        sessionStorage.setItem(SETTINGS_TOKEN_SESSION_KEY, value);
      } else {
        sessionStorage.removeItem(SETTINGS_TOKEN_SESSION_KEY);
      }
    } catch {
      // The token remains available for the current page.
    }
  };
  const storeCustomProfile = () => {
    saveCustomColor();
    setMessageTone("success");
    setMessage(t("Aktuelle Farbe wurde als Custom gespeichert."));
  };
  const applyProfile = (profileColor: string) => {
    updateColor(profileColor);
    setMessageTone("info");
    setMessage(t("Farbprofil ist lokal aktiv."));
  };
  const setGlobal = async (
    profile: AppearanceSettings["global_profile"],
    profileColor: string | null,
  ) => {
    if (!settingsToken.trim()) {
      setMessageTone("critical");
      setMessage(t("Settings-Token ist erforderlich."));
      return;
    }
    if (profile === "custom" && !profileColor) {
      setMessageTone("critical");
      setMessage(t("Speichere zuerst eine Custom-Farbe."));
      return;
    }
    setSavingGlobal(true);
    setMessage("");
    try {
      await updateGlobalAppearance(
        profile,
        profileColor,
        settingsToken.trim(),
      );
      setMessageTone("success");
      setMessage(t("Globaler Standard wurde aktualisiert."));
    } catch (reason) {
      const rawMessage =
        reason instanceof Error ? reason.message : t("Aktualisierung fehlgeschlagen.");
      setMessageTone("critical");
      setMessage(
        rawMessage === "Invalid settings token"
          ? t("Settings-Token ist ungültig.")
          : rawMessage,
      );
    } finally {
      setSavingGlobal(false);
    }
  };
  const activeLabel = hasLocalBrand
    ? t("Lokale Farbgebung aktiv")
    : appearance?.global_profile === "custom"
      ? t("Globaler Standard: Custom")
      : t("Globaler Standard: Standardgrün");

  return (
    <div className="page-stack settings-page">
      <SectionHeader
        title={t("Einstellungen")}
        subtitle={t("Sprache und visuelle Darstellung")}
        action={
          <StatusPill tone={hasLocalBrand ? "info" : "neutral"}>
            {activeLabel}
          </StatusPill>
        }
      />

      <div className="settings-grid">
        <section className="surface language-settings">
          <div className="settings-title">
            <span className="settings-icon">
              <Globe2 aria-hidden="true" />
            </span>
            <div>
              <h3>{t("Sprache")}</h3>
              <p>{t("Sprache der Benutzeroberfläche")}</p>
            </div>
          </div>
          <div className="language-toggle" role="group" aria-label={t("Sprache")}>
            <button
              type="button"
              className={classNames(language === "de" && "active")}
              aria-pressed={language === "de"}
              onClick={() => setLanguage("de")}
            >
              DE · {t("Deutsch")}
            </button>
            <button
              type="button"
              className={classNames(language === "en" && "active")}
              aria-pressed={language === "en"}
              onClick={() => setLanguage("en")}
            >
              EN · {t("Englisch")}
            </button>
          </div>
        </section>

        <section className="surface brand-settings">
          <div className="settings-title">
            <span className="settings-icon">
              <Palette aria-hidden="true" />
            </span>
            <div>
              <h3>{t("UI-Farbgebung")}</h3>
              <p>
                {t(
                  "Die Grundfarbe steuert Navigation, Akzente, Fokus sowie die feine Tönung von Karten, Flächen und Trennlinien. Statusfarben für Fehler und Warnungen bleiben semantisch eindeutig.",
                )}
              </p>
            </div>
          </div>

          <div className="color-picker-row">
            <label className="color-picker-label">
              <span>{t("Aktuelle Farbe")}</span>
              <input
                className="color-picker"
                type="color"
                value={color}
                onChange={(event) => updateColor(event.target.value)}
              />
            </label>
            <div className="color-value" aria-live="polite">
              <span
                className="color-swatch"
                style={{ backgroundColor: color }}
                aria-hidden="true"
              />
              <div>
                <strong>{color.toUpperCase()}</strong>
                <small>
                  RGB {rgb.r} / {rgb.g} / {rgb.b}
                </small>
              </div>
            </div>
          </div>

          <div className="rgb-grid" aria-label={t("RGB-Farbwerte")}>
            {(["r", "g", "b"] as const).map((channel) => (
              <label key={channel}>
                <span>{channel.toUpperCase()}</span>
                <input
                  type="number"
                  min={0}
                  max={255}
                  inputMode="numeric"
                  value={rgb[channel]}
                  onChange={(event) =>
                    updateChannel(channel, event.target.value)
                  }
                />
              </label>
            ))}
          </div>

          <div className="editor-actions">
            <button
              className="button button-primary"
              type="button"
              onClick={storeCustomProfile}
            >
              <Save aria-hidden="true" />
              {t("Als Custom speichern")}
            </button>
            {hasLocalBrand && (
              <button
                className="button button-ghost"
                type="button"
                onClick={resetLocalBrand}
              >
                {t("Lokale Abweichung entfernen")}
              </button>
            )}
          </div>
          <div className="settings-note">
            <Info aria-hidden="true" />
            <span>
              {t(
                "Änderungen wirken sofort und bleiben automatisch in diesem Browser gespeichert.",
              )}
            </span>
          </div>
        </section>

        <section className="surface brand-preview-section">
          <div>
            <h3>{t("Live-Vorschau")}</h3>
            <p>
              {t(
                "Änderungen werden unmittelbar auf die gesamte Oberfläche angewendet.",
              )}
            </p>
          </div>
          <div className="brand-preview">
            <div className="preview-brand">
              <span className="brand-mark">
                <ShieldCheck aria-hidden="true" />
              </span>
              <div>
                <strong>DMARC Control</strong>
                <small>{t("Gebrandete Oberfläche")}</small>
              </div>
            </div>
            <div className="preview-navigation">
              <span className="preview-active">{t("Aktiver Bereich")}</span>
              <span>{t("Inaktiver Bereich")}</span>
            </div>
            <div className="preview-content">
              <span className="preview-accent" />
              <div>
                <strong>{t("Akzent und Fading")}</strong>
                <small>
                  {t("Akzente und Flächentöne aus {color} abgeleitet", {
                    color: color.toUpperCase(),
                  })}
                </small>
              </div>
              <button className="button button-primary" type="button">
                {t("Beispielaktion")}
              </button>
            </div>
          </div>
          <div className="settings-note">
            <Info aria-hidden="true" />
            <span>
              {t(
                "Die Vorschau verändert keine DMARC- oder OpenSearch-Daten.",
              )}
            </span>
          </div>
        </section>

        <section className="surface profile-settings">
          <div className="settings-title">
            <span className="settings-icon">
              <Palette aria-hidden="true" />
            </span>
            <div>
              <h3>{t("Farbprofile")}</h3>
              <p>
                {t(
                  "Profile können lokal angewendet oder als Standard für alle Browser dieser Installation gesetzt werden.",
                )}
              </p>
            </div>
          </div>

          <div className="profile-grid">
            <article
              className={classNames(
                "profile-card",
                appearance?.global_profile === "custom" && "global",
              )}
            >
              <div className="profile-card-head">
                <span
                  className={classNames(
                    "preset-swatch",
                    !customColor && "empty",
                  )}
                  style={
                    customColor
                      ? { backgroundColor: customColor }
                      : undefined
                  }
                  aria-hidden="true"
                />
                <div>
                  <strong>{t("Custom")}</strong>
                  <small>
                    {customColor && customRgb
                      ? `${customColor.toUpperCase()} · RGB ${customRgb.r} / ${customRgb.g} / ${customRgb.b}`
                      : t("Noch nicht gespeichert")}
                  </small>
                </div>
                {appearance?.global_profile === "custom" && (
                  <StatusPill tone="info">{t("Global")}</StatusPill>
                )}
              </div>
              <div className="profile-actions">
                <button
                  className="button button-secondary"
                  type="button"
                  disabled={!customColor}
                  onClick={() => customColor && applyProfile(customColor)}
                >
                  {t("Anwenden")}
                </button>
                <button
                  className="button button-ghost"
                  type="button"
                  disabled={!customColor || savingGlobal}
                  onClick={() => setGlobal("custom", customColor)}
                >
                  {t("Global setzen")}
                </button>
              </div>
            </article>

            <article
              className={classNames(
                "profile-card",
                appearance?.global_profile === "standard" && "global",
              )}
            >
              <div className="profile-card-head">
                <span
                  className="preset-swatch"
                  style={{ backgroundColor: DEFAULT_BRAND_COLOR }}
                  aria-hidden="true"
                />
                <div>
                  <strong>{t("Standardgrün")}</strong>
                  <small>{DEFAULT_BRAND_COLOR.toUpperCase()}</small>
                </div>
                {appearance?.global_profile === "standard" && (
                  <StatusPill tone="info">{t("Global")}</StatusPill>
                )}
              </div>
              <div className="profile-actions">
                <button
                  className="button button-secondary"
                  type="button"
                  onClick={() => applyProfile(DEFAULT_BRAND_COLOR)}
                >
                  {t("Anwenden")}
                </button>
                <button
                  className="button button-ghost"
                  type="button"
                  disabled={savingGlobal}
                  onClick={() => setGlobal("standard", null)}
                >
                  {t("Global setzen")}
                </button>
              </div>
            </article>
          </div>

          <div className="global-settings-auth">
            <div>
              <LockKeyhole aria-hidden="true" />
              <div>
                <strong>{t("Geschützte globale Einstellung")}</strong>
                <small>
                  {t(
                    "Der Token wird nur für diese Browser-Sitzung gespeichert.",
                  )}
                </small>
              </div>
            </div>
            <label>
              <span>{t("Settings-Token")}</span>
              <input
                type="password"
                autoComplete="off"
                value={settingsToken}
                placeholder={t("Token für globale Änderungen")}
                onChange={(event) => updateToken(event.target.value)}
              />
            </label>
          </div>

          {appearance && !appearance.token_configured && !appearanceError && (
            <div className="inline-warning">
              <TriangleAlert aria-hidden="true" />
              {t("Auf dem Server ist noch kein Settings-Token eingerichtet.")}
            </div>
          )}
          {appearanceError && (
            <div className="inline-warning">
              <TriangleAlert aria-hidden="true" />
              {t("Globale Farbgebung ist nicht verfügbar: {error}", {
                error: appearanceError,
              })}
            </div>
          )}
          {message && (
            <div className="settings-feedback" aria-live="polite">
              <StatusPill tone={messageTone}>{message}</StatusPill>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function OverviewView({
  domain,
  days,
  refreshKey,
  openAlerts,
  openHosts,
}: {
  domain: string;
  days: number;
  refreshKey: number;
  openAlerts: () => void;
  openHosts: () => void;
}) {
  const {
    t,
    formatNumber,
    formatPercent,
    formatDate,
    reportAge,
    translateBackendLabel,
  } = useI18n();
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    api
      .overview(domain, days)
      .then(setData)
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  }, [domain, days]);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  if (loading && !data) return <LoadingState />;
  if (error && !data) return <ErrorState message={error} retry={load} />;
  if (!data) return null;

  const total = data.totals.messages;
  const compensated =
    Math.max(0, data.alignment.spf_not_aligned - data.totals.dmarc_fail) +
    Math.max(0, data.alignment.dkim_not_aligned - data.totals.dmarc_fail);

  return (
    <div className="page-stack">
      {error && <ErrorState message={error} retry={load} />}
      <section className="kpi-grid" aria-label={t("DMARC-Kennzahlen")}>
        <article className="card kpi">
          <div className="kpi-label">
            <span>{t("DMARC-Passrate")}</span>
            <ShieldCheck aria-hidden="true" />
          </div>
          <strong>{formatPercent(data.totals.pass_rate)} %</strong>
          <p>
            {t("{passed} von {total} Nachrichten", {
              passed: formatNumber(data.totals.dmarc_pass),
              total: formatNumber(total),
            })}
          </p>
        </article>
        <article className="card kpi">
          <div className="kpi-label">
            <span>{t("Nachrichten")}</span>
            <Activity aria-hidden="true" />
          </div>
          <strong>{formatNumber(total)}</strong>
          <p>
            {t("Letzter Report: {date}", {
              date: formatDate(data.totals.last_report),
            })}{" "}
            · {reportAge(data.totals.last_report)}
          </p>
        </article>
        <article className="card kpi kpi-critical">
          <div className="kpi-label">
            <span>{t("Kritische Quellen")}</span>
            <TriangleAlert aria-hidden="true" />
          </div>
          <strong>{formatNumber(data.totals.critical_sources)}</strong>
          <p>
            {t("{count} echte DMARC-Fails", {
              count: formatNumber(data.totals.dmarc_fail),
            })}
          </p>
        </article>
      </section>

      <div className="overview-grid">
        <section className="surface attention-panel">
          <SectionHeader
            title={t("Was braucht Aufmerksamkeit?")}
            subtitle={t(
              "Nach finalem DMARC-Ergebnis und Aktualität priorisiert",
            )}
            action={
              <button className="text-button" type="button" onClick={openAlerts}>
                {t("Alle Warnungen")} <ChevronRight aria-hidden="true" />
              </button>
            }
          />
          {data.critical_sources.length ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>{t("Status")}</th>
                    <th>{t("Sending Host")}</th>
                    <th>{t("Domain")}</th>
                    <th>{t("Authentifizierung")}</th>
                    <th className="numeric">{t("Nachrichten")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.critical_sources.slice(0, 8).map((source) => (
                    <tr key={`${source.source_ip}-${source.header_from}`}>
                      <td>
                        <StatusPill tone="critical">{t("Kritisch")}</StatusPill>
                      </td>
                      <td>
                        <button className="cell-link" type="button" onClick={openHosts}>
                          <IpWithFlag
                            ip={source.source_ip}
                            country={source.country}
                          />
                          <small>{source.reverse_dns || t("Kein PTR")}</small>
                        </button>
                      </td>
                      <td>
                        <span>{source.header_from || "–"}</span>
                        <small>
                          {translateBackendLabel(source.country) ||
                            t("Unbekannt")}
                        </small>
                      </td>
                      <td>
                        <span className="auth-pair">
                          SPF{" "}
                          {source.spf_aligned
                            ? t("aligned")
                            : t("nicht aligned")}
                        </span>
                        <small>
                          DKIM{" "}
                          {source.dkim_aligned
                            ? t("aligned")
                            : t("nicht aligned")}
                        </small>
                      </td>
                      <td className="numeric">
                        <strong>{formatNumber(source.messages)}</strong>
                        <small>{formatDate(source.last_seen)}</small>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              title={t("Keine echten DMARC-Fehler")}
              description={t(
                "Im gewählten Zeitraum sind keine Quellen mit passed_dmarc:false vorhanden.",
              )}
            />
          )}
        </section>

        <section className="surface alignment-panel">
          <SectionHeader
            title={t("Authentifizierung")}
            subtitle={t("Alignment gegenüber finalem DMARC-Ergebnis")}
          />
          <div className="alignment-list">
            <AlignmentBar
              label={t("DMARC bestanden")}
              value={data.alignment.dmarc_pass}
              total={total}
              tone="success"
            />
            <AlignmentBar
              label="DKIM aligned"
              value={data.alignment.dkim_aligned}
              total={total}
              tone="info"
            />
            <AlignmentBar
              label="SPF aligned"
              value={data.alignment.spf_aligned}
              total={total}
              tone="warning"
            />
            <AlignmentBar
              label={t("DMARC fehlgeschlagen")}
              value={data.alignment.dmarc_fail}
              total={total}
              tone="danger"
            />
          </div>
          <div className="insight">
            <Info aria-hidden="true" />
            <p>
              {compensated
                ? t(
                    "{count} Alignment-Beobachtungen wurden durch den jeweils anderen Mechanismus kompensiert und sind deshalb keine kritischen DMARC-Fails.",
                    { count: formatNumber(compensated) },
                  )
                : t(
                    "Alignment und finales DMARC-Ergebnis sind im gewählten Zeitraum konsistent.",
                  )}
            </p>
          </div>
        </section>
      </div>

      <section className="surface">
        <SectionHeader
          title={t("DMARC Pass/Fail im Zeitverlauf")}
          subtitle={t("Tageswerte für {scope}", {
            scope: domain === "*" ? t("alle Domains") : domain,
          })}
        />
        <TrendChart data={data.trend} />
      </section>

      <section>
        <SectionHeader
          title={t("Domains & Reports")}
          subtitle={t(
            "Volumen, Berichtsersteller und veröffentlichte Richtlinien",
          )}
        />
        <div className="three-column-grid">
          <article className="surface compact-surface">
            <h3>{t("Nachrichten nach Domain")}</h3>
            <TopList
              items={data.domains.slice(0, 8).map((item) => ({
                name: item.name,
                value: item.messages,
              }))}
              empty={t("Keine Domains im Zeitraum")}
            />
          </article>
          <article className="surface compact-surface">
            <h3>{t("Reporting Organizations")}</h3>
            <TopList
              items={data.reporting_organisations.slice(0, 8).map((item) => ({
                name: item.name,
                value: item.messages,
              }))}
              empty={t("Keine Berichtsersteller im Zeitraum")}
            />
          </article>
          <article className="surface compact-surface">
            <h3>{t("Veröffentlichte DMARC-Policies")}</h3>
            {data.policies.length ? (
              <div className="policy-list">
                {data.policies.slice(0, 8).map((item) => (
                  <div key={item.domain}>
                    <span className="truncate">{item.domain}</span>
                    <StatusPill
                      tone={item.policy === "reject" ? "success" : "neutral"}
                    >
                      p={item.policy} · {item.percentage} %
                    </StatusPill>
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted compact-empty">
                {t("Keine Policies im Zeitraum")}
              </p>
            )}
          </article>
        </div>
      </section>
    </div>
  );
}

function HostsView({
  domain,
  days,
  refreshKey,
}: {
  domain: string;
  days: number;
  refreshKey: number;
}) {
  const { t, formatNumber, formatDate, translateBackendLabel } = useI18n();
  const [hosts, setHosts] = useState<Host[]>([]);
  const [risk, setRisk] = useState("all");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Host | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    api
      .hosts(domain, days, risk)
      .then((items) => {
        setHosts(items);
        if (selected) {
          setSelected(
            items.find((item) => item.source_ip === selected.source_ip) ?? null,
          );
        }
      })
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  }, [domain, days, risk, selected?.source_ip]);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return hosts;
    return hosts.filter((host) =>
      [
        host.source_ip,
        host.reverse_dns,
        host.base_domain,
        host.service_detection.service,
        host.as_name,
        ...host.header_froms,
        ...host.envelope_froms,
      ]
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [hosts, search]);

  if (loading && !hosts.length) {
    return <LoadingState label={t("Sending Hosts werden geladen")} />;
  }
  if (error && !hosts.length) return <ErrorState message={error} retry={load} />;

  return (
    <div className="page-stack">
      <SectionHeader
        title="Sending Hosts"
        subtitle={t(
          "Technische Quellen, erkannte Dienste und Authentifizierungsergebnis",
        )}
        action={
          <StatusPill tone="neutral">
            {t("{count} Quellen", { count: filtered.length })}
          </StatusPill>
        }
      />
      <div className="list-toolbar">
        <label className="search-field">
          <Search aria-hidden="true" />
          <span className="sr-only">{t("Sending Hosts durchsuchen")}</span>
          <input
            type="search"
            placeholder={t("IP, PTR, Domain oder Dienst suchen")}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <label className="compact-select">
          <span>{t("Risiko")}</span>
          <select value={risk} onChange={(event) => setRisk(event.target.value)}>
            <option value="all">{t("Alle Ergebnisse")}</option>
            <option value="critical">{t("Kritisch")}</option>
            <option value="warning">{t("Hinweise")}</option>
            <option value="healthy">{t("Unauffällig")}</option>
            <option value="spf-not-aligned">{t("SPF nicht aligned")}</option>
            <option value="dkim-not-aligned">{t("DKIM nicht aligned")}</option>
          </select>
        </label>
      </div>

      {error && <ErrorState message={error} retry={load} />}

      <section className="surface">
        {filtered.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("Source")}</th>
                  <th>{t("Erkannter Dienst")}</th>
                  <th>{t("Vertrauen")}</th>
                  <th>Alignment</th>
                  <th>DMARC</th>
                  <th className="numeric">{t("Nachrichten")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {filtered.map((host) => (
                  <tr
                    className={selected?.source_ip === host.source_ip ? "selected-row" : ""}
                    key={host.source_ip}
                  >
                    <td>
                      <IpWithFlag ip={host.source_ip} country={host.country} />
                      <small>{host.reverse_dns || t("Kein PTR")}</small>
                      <small>
                        {[
                          translateBackendLabel(host.country),
                          host.as_name,
                        ]
                          .filter(Boolean)
                          .join(" · ") || "–"}
                      </small>
                    </td>
                    <td>
                      <strong>
                        {translateBackendLabel(host.service_detection.service)}
                      </strong>
                      <small>
                        {t("Konfidenz")}{" "}
                        {translateBackendLabel(
                          host.service_detection.confidence_label,
                        )}{" "}
                        ·{" "}
                        {Math.round(host.service_detection.confidence * 100)} %
                      </small>
                    </td>
                    <td>
                      <TrustPill status={host.trust_status} />
                    </td>
                    <td>
                      <span>
                        SPF{" "}
                        {host.spf_not_aligned
                          ? `${formatNumber(host.spf_not_aligned)} ${t(
                              "nicht aligned",
                            )}`
                          : t("aligned")}
                      </span>
                      <small>
                        DKIM{" "}
                        {host.dkim_not_aligned
                          ? `${formatNumber(host.dkim_not_aligned)} ${t(
                              "nicht aligned",
                            )}`
                          : t("aligned")}
                      </small>
                    </td>
                    <td>
                      <RiskPill host={host} />
                    </td>
                    <td className="numeric">
                      <strong>{formatNumber(host.messages)}</strong>
                      <small>{formatDate(host.last_seen)}</small>
                    </td>
                    <td className="numeric">
                      <button
                        className="button button-ghost"
                        type="button"
                        onClick={() => setSelected(host)}
                      >
                        {t("Details")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            title={t("Keine Sending Hosts gefunden")}
            description={t("Passe Suche, Zeitraum oder Risikofilter an.")}
          />
        )}
      </section>

      {selected && (
        <HostDetail host={selected} close={() => setSelected(null)} saved={load} />
      )}
    </div>
  );
}

function RiskPill({ host }: { host: Host }) {
  const { t, formatNumber } = useI18n();
  if (host.risk === "critical") {
    return (
      <StatusPill tone="critical">
        Fail · {formatNumber(host.dmarc_fail)}
      </StatusPill>
    );
  }
  if (host.risk === "warning") {
    return <StatusPill tone="warning">{t("Pass · Hinweis")}</StatusPill>;
  }
  return <StatusPill tone="success">Pass</StatusPill>;
}

function TrustPill({ status }: { status: TrustStatus }) {
  const { language, t } = useI18n();
  const values: Record<TrustStatus, { label: string; tone: "neutral" | "info" | "success" }> = {
    unconfirmed: { label: t("Nicht bestätigt"), tone: "neutral" },
    automatic: { label: t("Automatisch erkannt"), tone: "info" },
    confirmed: {
      label: language === "en" ? "Confirmed" : "Bestätigt",
      tone: "success",
    },
    ignored: { label: t("Ignoriert"), tone: "neutral" },
  };
  const value = values[status];
  return <StatusPill tone={value.tone}>{value.label}</StatusPill>;
}

function HostDetail({
  host,
  close,
  saved,
}: {
  host: Host;
  close: () => void;
  saved: () => void;
}) {
  const { language, t, formatNumber, formatDate, translateBackendLabel } =
    useI18n();
  const [serviceName, setServiceName] = useState(host.service_detection.service);
  const [trustStatus, setTrustStatus] = useState<TrustStatus>(host.trust_status);
  const [notes, setNotes] = useState(host.override?.notes ?? "");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    setServiceName(host.service_detection.service);
    setTrustStatus(host.trust_status);
    setNotes(host.override?.notes ?? "");
  }, [host]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setMessage("");
    try {
      await api.updateHost(host.source_ip, {
        service_name: serviceName.trim() || null,
        trust_status: trustStatus,
        notes: notes.trim() || null,
      });
      setMessage(t("Zuordnung gespeichert."));
      saved();
    } catch (reason) {
      setMessage(
        reason instanceof Error ? reason.message : t("Speichern fehlgeschlagen"),
      );
    } finally {
      setSaving(false);
    }
  };

  const evidence = [
    ...(host.service_detection.evidence ?? []),
    host.reverse_dns ? `PTR: ${host.reverse_dns}` : t("PTR: nicht vorhanden"),
    host.asn
      ? `ASN ${host.asn}: ${host.as_name ?? t("Unbekannt")}`
      : "",
  ]
    .filter(Boolean)
    .map((item) => translateBackendLabel(item));

  return (
    <section className="surface host-detail" aria-live="polite">
      <div className="host-detail-head">
        <div>
          <div className="eyebrow">{t("Host-Detail")}</div>
          <h2>
            <IpWithFlag ip={host.source_ip} country={host.country} />
          </h2>
          <p>{host.reverse_dns || t("Kein Reverse-DNS-Name vorhanden")}</p>
        </div>
        <div className="host-detail-actions">
          <RiskPill host={host} />
          <button
            className="icon-button"
            type="button"
            onClick={close}
            aria-label={t("Detailansicht schließen")}
          >
            <X aria-hidden="true" />
          </button>
        </div>
      </div>

      <div className="detail-grid">
        <Detail label="Header From" value={host.header_froms.join(", ") || "–"} />
        <Detail label="Envelope From" value={host.envelope_froms.join(", ") || "–"} />
        <Detail
          label={t("SPF-Identitäten")}
          value={host.spf_domains.join(", ") || "–"}
        />
        <Detail
          label={t("DKIM-Domains")}
          value={host.dkim_domains.join(", ") || "–"}
        />
        <Detail
          label={t("DKIM-Selector")}
          value={host.dkim_selectors.join(", ") || "–"}
        />
        <Detail
          label={t("Netzwerk")}
          value={[
            translateBackendLabel(host.country),
            host.asn ? `AS${host.asn}` : null,
            host.as_name,
          ]
            .filter(Boolean)
            .join(" · ") || "–"}
        />
        <Detail
          label={t("Erstmals gesehen")}
          value={formatDate(host.first_seen, true)}
        />
        <Detail
          label={t("Zuletzt gesehen")}
          value={formatDate(host.last_seen, true)}
        />
        <Detail
          label={t("DMARC-Ergebnis")}
          value={`${formatNumber(host.dmarc_pass)} Pass · ${formatNumber(host.dmarc_fail)} Fail`}
        />
      </div>

      <div className="evidence-block">
        <div>
          <h3>{t("Dienst-Erkennung")}</h3>
          <p>
            {t(
              "Mehrere Signale werden kombiniert. PTR ist nur ein Indiz und niemals die alleinige Entscheidungsgrundlage.",
            )}
          </p>
        </div>
        <div className="evidence-list">
          {evidence.map((item) => (
            <span className="evidence-chip" key={item}>
              <Check aria-hidden="true" />
              {item}
            </span>
          ))}
          {!evidence.length && (
            <span className="muted">{t("Keine belastbare Evidenz.")}</span>
          )}
        </div>
      </div>

      <form className="classification-form" onSubmit={submit}>
        <label>
          <span>{t("Dienst")}</span>
          <input
            value={serviceName}
            maxLength={120}
            onChange={(event) => setServiceName(event.target.value)}
          />
        </label>
        <label>
          <span>{t("Vertrauensstatus")}</span>
          <select
            value={trustStatus}
            onChange={(event) => setTrustStatus(event.target.value as TrustStatus)}
          >
            <option value="unconfirmed">{t("Nicht bestätigt")}</option>
            <option value="automatic">{t("Automatisch erkannt")}</option>
            <option value="confirmed">
              {language === "en" ? "Confirmed" : "Bestätigt"}
            </option>
            <option value="ignored">{t("Ignoriert")}</option>
          </select>
        </label>
        <label className="notes-field">
          <span>{t("Notiz")}</span>
          <input
            value={notes}
            maxLength={500}
            placeholder={t("Optionaler administrativer Kontext")}
            onChange={(event) => setNotes(event.target.value)}
          />
        </label>
        <button className="button button-primary" type="submit" disabled={saving}>
          {saving ? <RefreshCw className="spin" aria-hidden="true" /> : <Save aria-hidden="true" />}
          {t("Speichern")}
        </button>
        {message && <span className="form-message">{message}</span>}
      </form>
    </section>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="detail-item">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function AlertsView({
  domain,
  days,
  refreshKey,
}: {
  domain: string;
  days: number;
  refreshKey: number;
}) {
  const { language, t, formatNumber, formatDate, reportAge } = useI18n();
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [status, setStatus] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [updating, setUpdating] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    api
      .alerts(domain, days, status)
      .then(setAlerts)
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  }, [domain, days, status]);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  const update = async (alertId: string, nextStatus: AlertStatus) => {
    setUpdating(alertId);
    try {
      await api.updateAlert(alertId, nextStatus);
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : t("Statusänderung fehlgeschlagen"),
      );
    } finally {
      setUpdating("");
    }
  };

  if (loading && !alerts.length) {
    return <LoadingState label={t("Warnungen werden bewertet")} />;
  }
  if (error && !alerts.length) return <ErrorState message={error} retry={load} />;

  const openCount = alerts.filter((item) => item.status === "open").length;
  const alertTitle = (alert: Alert) => t(alert.title);
  const alertTrigger = (alert: Alert) => {
    if (language === "de") return alert.trigger;
    if (alert.kind === "new-source-ip") {
      const date = alert.trigger.match(/\d{4}-\d{2}-\d{2}/)?.[0] ?? "–";
      return t("Erstmals gesehen am {date}", { date });
    }
    if (alert.kind === "compensated-alignment") {
      const mechanisms = [
        alert.trigger.includes("SPF") ? t("SPF nicht aligned") : "",
        alert.trigger.includes("DKIM") ? t("DKIM nicht aligned") : "",
      ].filter(Boolean);
      return `${mechanisms.join(", ")} · ${t("DMARC bestanden")}`;
    }
    if (alert.kind === "stale-reports") {
      const days = Math.max(
        0,
        Math.floor(
          (Date.now() - new Date(alert.report_time ?? "").getTime()) /
            86_400_000,
        ),
      );
      return t(
        "Letzter Report vor {days} Tagen; übliche Zustellverzögerung berücksichtigt",
        { days },
      );
    }
    return alert.trigger;
  };
  return (
    <div className="page-stack">
      <SectionHeader
        title={t("Warnungszentrale")}
        subtitle={t(
          "Deduplizierte Ereignisse mit nachvollziehbarem Auslöser",
        )}
        action={
          <StatusPill tone={openCount ? "critical" : "success"}>
            {t("{count} offen", { count: openCount })}
          </StatusPill>
        }
      />
      <div className="list-toolbar align-end">
        <label className="compact-select">
          <span>{t("Status")}</span>
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="all">{t("Alle Status")}</option>
            <option value="open">{t("Offen")}</option>
            <option value="acknowledged">{t("Bestätigt")}</option>
            <option value="resolved">{t("Behoben")}</option>
            <option value="ignored">{t("Ignoriert")}</option>
          </select>
        </label>
      </div>
      {error && <ErrorState message={error} retry={load} />}
      <section className="surface">
        {alerts.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("Priorität")}</th>
                  <th>{t("Warnung")}</th>
                  <th>{t("Auslöser")}</th>
                  <th>{t("Reportzeit")}</th>
                  <th>{t("Status")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {alerts.map((alert) => (
                  <tr key={alert.id}>
                    <td><PriorityPill priority={alert.priority} /></td>
                    <td>
                      <strong>{alertTitle(alert)}</strong>
                      {alert.source_ip && (
                        <small>
                          <IpWithFlag
                            ip={alert.source_ip}
                            country={alert.country}
                          />
                        </small>
                      )}
                      <small>{alert.domain}</small>
                    </td>
                    <td>
                      <span>{alertTrigger(alert)}</span>
                      <small>
                        {formatNumber(alert.messages)} {t("Nachrichten")}
                      </small>
                    </td>
                    <td>
                      <span>{formatDate(alert.report_time)}</span>
                      <small>{reportAge(alert.report_time)}</small>
                    </td>
                    <td><AlertStatusPill status={alert.status} /></td>
                    <td className="numeric">
                      <div className="row-actions">
                        {alert.status === "open" && (
                          <button
                            className="button button-secondary"
                            type="button"
                            disabled={updating === alert.id}
                            onClick={() => update(alert.id, "acknowledged")}
                          >
                            {t("Bestätigen")}
                          </button>
                        )}
                        {alert.status !== "resolved" && (
                          <button
                            className="button button-ghost"
                            type="button"
                            disabled={updating === alert.id}
                            onClick={() => update(alert.id, "resolved")}
                          >
                            {t("Behoben")}
                          </button>
                        )}
                        {alert.status !== "ignored" && (
                          <button
                            className="button button-ghost"
                            type="button"
                            disabled={updating === alert.id}
                            onClick={() => update(alert.id, "ignored")}
                          >
                            {t("Ignorieren")}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            title={t("Keine Warnungen in dieser Ansicht")}
            description={t(
              "Für Domain, Zeitraum und Status existieren keine passenden Ereignisse.",
            )}
          />
        )}
      </section>

      <section className="alert-logic-grid">
        <article className="logic-item">
          <TriangleAlert aria-hidden="true" />
          <div>
            <strong>{t("Sofort kritisch")}</strong>
            <span>
              {t("Neuer oder nicht autorisierter Host mit echtem DMARC-Fail.")}
            </span>
          </div>
        </article>
        <article className="logic-item">
          <Info aria-hidden="true" />
          <div>
            <strong>{t("Konfigurationshinweis")}</strong>
            <span>
              {t(
                "Ein Mechanismus ist nicht aligned, DMARC besteht aber weiterhin.",
              )}
            </span>
          </div>
        </article>
        <article className="logic-item">
          <Clock3 aria-hidden="true" />
          <div>
            <strong>{t("Report-Verzögerung")}</strong>
            <span>
              {t(
                "Ausbleibende Reports werden erst nach der üblichen Verzögerung gewarnt.",
              )}
            </span>
          </div>
        </article>
      </section>
    </div>
  );
}

function PriorityPill({ priority }: { priority: Alert["priority"] }) {
  const { t } = useI18n();
  if (priority === "critical") {
    return <StatusPill tone="critical">{t("Kritisch")}</StatusPill>;
  }
  if (priority === "warning") {
    return <StatusPill tone="warning">{t("Warnung")}</StatusPill>;
  }
  return <StatusPill tone="info">{t("Hinweis")}</StatusPill>;
}

function AlertStatusPill({ status }: { status: AlertStatus }) {
  const { t } = useI18n();
  const values: Record<AlertStatus, { label: string; tone: "critical" | "info" | "success" | "neutral" }> = {
    open: { label: t("Offen"), tone: "critical" },
    acknowledged: { label: t("Bestätigt"), tone: "info" },
    resolved: { label: t("Behoben"), tone: "success" },
    ignored: { label: t("Ignoriert"), tone: "neutral" },
  };
  const value = values[status];
  return <StatusPill tone={value.tone}>{value.label}</StatusPill>;
}

function ForensicsView({
  domain,
  days,
  refreshKey,
}: {
  domain: string;
  days: number;
  refreshKey: number;
}) {
  const {
    t,
    formatNumber,
    formatDate,
    reportAge,
    translateBackendLabel,
  } = useI18n();
  const [data, setData] = useState<Forensics | null>(null);
  const [failureType, setFailureType] = useState("*");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    api
      .forensics(domain, days, failureType)
      .then(setData)
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  }, [domain, days, failureType]);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  if (loading && !data) {
    return <LoadingState label={t("Forensik-Metadaten werden geladen")} />;
  }
  if (error && !data) return <ErrorState message={error} retry={load} />;
  if (!data) return null;

  const failureOptions = data.failure_types.map((item) => item.name);
  return (
    <div className="page-stack">
      <SectionHeader
        title={t("DMARC Forensik")}
        subtitle={t("Minimierte Betriebsmetadaten aus RUF-/Failure-Reports")}
        action={
          <label className="compact-select">
            <span>{t("Fehlertyp")}</span>
            <select
              value={failureType}
              onChange={(event) => setFailureType(event.target.value)}
            >
              <option value="*">{t("Alle Fehlertypen")}</option>
              {failureOptions.map((item) => (
                <option value={item} key={item}>{item}</option>
              ))}
            </select>
          </label>
        }
      />
      <div className="privacy-banner">
        <EyeOff aria-hidden="true" />
        <div>
          <strong>Privacy by design</strong>
          <span>
            {t(
              "Rohinhalt, Empfänger, Absender, Betreff und Header werden von dieser API nicht geladen.",
            )}
          </span>
        </div>
      </div>
      {error && <ErrorState message={error} retry={load} />}
      <section className="kpi-grid">
        <article className="card kpi">
          <div className="kpi-label">
            <span>{t("Forensic Samples")}</span>
            <Database aria-hidden="true" />
          </div>
          <strong>{formatNumber(data.samples)}</strong>
          <p>{t("Aggregierte Failure-Metadaten")}</p>
        </article>
        <article className="card kpi">
          <div className="kpi-label">
            <span>{t("Datenaktualität")}</span>
            <Clock3 aria-hidden="true" />
          </div>
          <strong className="date-value">{formatDate(data.last_report)}</strong>
          <p>{reportAge(data.last_report)}</p>
        </article>
        <article className="card kpi">
          <div className="kpi-label">
            <span>{t("Source-IPs")}</span>
            <Globe2 aria-hidden="true" />
          </div>
          <strong>{formatNumber(data.sources.length)}</strong>
          <p>
            {t("{count} Länder/Zuordnungen", {
              count: formatNumber(data.countries.length),
            })}
          </p>
        </article>
      </section>

      {!data.samples ? (
        <EmptyState
          title={t("Keine Forensik-Daten im Zeitraum")}
          description={t(
            "RUF-Daten sind möglicherweise deaktiviert oder es sind keine passenden Failure-Reports eingegangen.",
          )}
        />
      ) : (
        <>
          <div className="three-column-grid">
            <article className="surface compact-surface">
              <h3>{t("Authentication Failure Types")}</h3>
              <TopList
                items={data.failure_types.map((item) => ({
                  name: item.name,
                  value: item.samples,
                }))}
                empty={t("Keine Fehlertypen")}
              />
            </article>
            <article className="surface compact-surface">
              <h3>{t("Betroffene Domains")}</h3>
              <TopList
                items={data.domains.map((item) => ({
                  name: item.name,
                  value: item.samples,
                }))}
                empty={t("Keine Domains")}
              />
            </article>
            <article className="surface compact-surface">
              <h3>{t("Quellen nach Land")}</h3>
              <TopList
                items={data.countries.map((item) => ({
                  name: translateBackendLabel(item.name),
                  value: item.samples,
                }))}
                empty={t("Keine Länderinformationen")}
              />
            </article>
          </div>

          <section className="surface">
            <SectionHeader
              title={t("Top Forensic Source IPs")}
              subtitle={t(
                "IP, PTR, Basisdomain, Land und letzte Beobachtung",
              )}
            />
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Source-IP</th>
                    <th>{t("PTR / Basisdomain")}</th>
                    <th>{t("Land")}</th>
                    <th>{t("Zuletzt gesehen")}</th>
                    <th className="numeric">{t("Samples")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.sources.map((source) => (
                    <tr key={source.source_ip}>
                      <td>
                        <IpWithFlag
                          ip={source.source_ip}
                          country={source.country}
                        />
                      </td>
                      <td>
                        <span>{source.reverse_dns || "–"}</span>
                        <small>{source.base_domain || "–"}</small>
                      </td>
                      <td>{translateBackendLabel(source.country)}</td>
                      <td>{formatDate(source.last_seen, true)}</td>
                      <td className="numeric"><strong>{formatNumber(source.samples)}</strong></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="surface">
            <SectionHeader
              title={t("Bereinigte Failure-Evidenz")}
              subtitle={t(
                "Nur Authentifizierungs- und Delivery-Ergebnis; keine Nachrichteninhalte",
              )}
            />
            <div className="evidence-table">
              {data.evidence.map((item, index) => (
                <article key={`${item.authentication_result}-${index}`}>
                  <code>{item.authentication_result}</code>
                  <div>
                    {item.failure_types.map((failure) => (
                      <StatusPill tone="critical" key={failure}>{failure}</StatusPill>
                    ))}
                    {item.delivery_results.map((delivery) => (
                      <StatusPill tone="neutral" key={delivery}>{delivery}</StatusPill>
                    ))}
                    <span>
                      {formatNumber(item.samples)} {t("Samples")}
                    </span>
                  </div>
                </article>
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
