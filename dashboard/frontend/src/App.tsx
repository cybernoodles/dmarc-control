import {
  Activity,
  ArrowLeft,
  Bell,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Cloud,
  Clock3,
  Database,
  EyeOff,
  FileSearch,
  Globe2,
  HardDriveDownload,
  Info,
  LayoutDashboard,
  LockKeyhole,
  LogOut,
  Mail,
  Palette,
  PlugZap,
  RefreshCw,
  Save,
  Search,
  Send,
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
  useRef,
  useState,
} from "react";
import {
  Alert,
  AlertStatus,
  ApiError,
  AppearanceSettings,
  AuthStatus,
  BackupMode,
  BackupSettings,
  DomainItem,
  Forensics,
  Host,
  MailboxConnectionState,
  MailboxConnectionUpdate,
  MailboxProvider,
  NotificationCase,
  NotificationSettings,
  NotificationSettingsUpdate,
  Overview,
  TrustStatus,
  api,
} from "./api";
import { LanguageProvider, useI18n } from "./i18n";
import { TrendChart } from "./TrendChart";
import { RecipientDeliveryStatus } from "./RecipientDeliveryStatus";
import { AlertEvaluationMonitor } from "./AlertEvaluationMonitor";
import { AlertDeliveryBadge, AlertDeliveryPanel } from "./AlertDeliveryView";
import { HostClassificationForm, classificationMode } from "./HostClassificationForm";
import { HostServiceDetection } from "./HostServiceDetection";

import { UnsavedChangesProvider, useUnsavedChanges } from "./UnsavedChanges";
import { useInvestigationNavigation } from "./useInvestigationNavigation";
import { validDomain, type View } from "./investigationLocation";
import { useAlertUpdates } from "./useAlertUpdates";
import { DomainMonitoringSettings } from "./DomainMonitoringSettings";
import { isExpectedProviderPassAlert } from "./alertPresentation";
type SettingsSection =
  | "appearance"
  | "notifications"
  | "domains"
  | "connection"
  | "backup"
  | "administration";

const DEFAULT_BRAND_COLOR = "#173f43";
const BRAND_STORAGE_KEY = "dmarc-control-brand-color";
const CUSTOM_BRAND_STORAGE_KEY = "dmarc-control-custom-brand-color";

function classNames(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

function BackupModeSelector({
  value,
  onChange,
  disabled = false,
}: {
  value: BackupMode | "";
  onChange: (mode: BackupMode) => void;
  disabled?: boolean;
}) {
  const { t } = useI18n();
  const options: Array<{
    mode: BackupMode;
    title: string;
    description: string;
    icon: typeof Database;
  }> = [
    {
      mode: "integrated",
      title: t("Integrierte Dumps"),
      description: t(
        "DMARC Control erstellt automatisch geprüfte OpenSearch-Snapshots und verschlüsselte Steuerungsbackups.",
      ),
      icon: Database,
    },
    {
      mode: "external",
      title: t("Externe Sicherung"),
      description: t(
        "VM oder Host werden bereits anwendungskonsistent einschließlich aller persistenten Daten gesichert.",
      ),
      icon: Cloud,
    },
    {
      mode: "none",
      title: t("Kein Backup"),
      description: t(
        "Nur für Testsysteme. Bei einem Ausfall gehen Historie und Steuerungszustand verloren.",
      ),
      icon: CircleAlert,
    },
  ];

  return (
    <div className="backup-mode-grid" role="radiogroup" aria-label={t("Backup-Strategie")}>
      {options.map((option) => {
        const Icon = option.icon;
        return (
          <label
            className={classNames(
              "backup-mode-option",
              value === option.mode && "selected",
            )}
            key={option.mode}
          >
            <input
              type="radio"
              name="backup-mode"
              value={option.mode}
              checked={value === option.mode}
              disabled={disabled}
              onChange={() => onChange(option.mode)}
            />
            <Icon aria-hidden="true" />
            <span>
              <strong>{option.title}</strong>
              <small>{option.description}</small>
            </span>
          </label>
        );
      })}
    </div>
  );
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
      <UnsavedChangesProvider><AppGate /></UnsavedChangesProvider>
    </LanguageProvider>
  );
}

function AppGate() {
  const { language, setLanguage, t } = useI18n();
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [error, setError] = useState("");
  const [preserveDraft, setPreserveDraft] = useState(false);
  const { hasUnsavedChanges, cancelPendingNavigation } = useUnsavedChanges();
  const completeAuthentication = (status: AuthStatus) => {
    setPreserveDraft(false);
    setAuth(status);
  };

  const loadStatus = useCallback(() => {
    setError("");
    api.authStatus().then(setAuth).catch((reason: Error) => setError(reason.message));
  }, []);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  useEffect(() => {
    const handleExpiredReadSession = () => {
      setPreserveDraft(hasUnsavedChanges());
      cancelPendingNavigation();
      setAuth((current) =>
        current
          ? {
              ...current,
              read_authenticated: false,
              read_username: null,
              authenticated: false,
            }
          : current,
      );
    };
    window.addEventListener(
      "dmarc-read-session-expired",
      handleExpiredReadSession,
    );
    return () =>
      window.removeEventListener(
        "dmarc-read-session-expired",
        handleExpiredReadSession,
      );
  }, [hasUnsavedChanges, cancelPendingNavigation]);

  if (!auth) {
    return (
      <div className="setup-shell">
        <section className="setup-card" aria-live="polite">
          <span className="brand-mark setup-brand-mark">
            <ShieldCheck aria-hidden="true" />
          </span>
          <strong>DMARC Control</strong>
          {error ? (
            <>
              <p>{t("Die Anwendung konnte nicht gestartet werden.")}</p>
              <small>{error}</small>
              <button
                className="button button-primary"
                type="button"
                onClick={loadStatus}
              >
                {t("Erneut versuchen")}
              </button>
            </>
          ) : (
            <p>{t("Sichere Anwendung wird vorbereitet …")}</p>
          )}
        </section>
      </div>
    );
  }

  if (auth.setup_required) {
    return (
      <AdminSetup
        adminConfigured={auth.admin_configured}
        language={language}
        setLanguage={setLanguage}
        onComplete={completeAuthentication}
      />
    );
  }

  if (auth.read_authenticated && auth.backup_setup_required) {
    return (
      <BackupStrategySetup
        language={language}
        setLanguage={setLanguage}
        onComplete={setAuth}
      />
    );
  }

  return <>
    {!auth.read_authenticated && <>
      {preserveDraft && <p className="session-draft-notice" role="status">
        {t("Deine Sitzung ist abgelaufen. Ungespeicherte Host-Änderungen bleiben für die erneute Anmeldung in diesem Tab erhalten.")}
      </p>}
      <ReadLogin language={language} setLanguage={setLanguage} onComplete={completeAuthentication} />
    </>}
    {(auth.read_authenticated || preserveDraft) && (
      <div hidden={!auth.read_authenticated} inert={!auth.read_authenticated}>
        <DashboardApp auth={auth} setAuth={completeAuthentication} />
      </div>
    )}
  </>;
}

function AdminSetup({
  adminConfigured,
  language,
  setLanguage,
  onComplete,
}: {
  adminConfigured: boolean;
  language: "de" | "en";
  setLanguage: (language: "de" | "en") => void;
  onComplete: (status: AuthStatus) => void;
}) {
  const { t } = useI18n();
  const [adminPassword, setAdminPassword] = useState("");
  const [adminConfirmation, setAdminConfirmation] = useState("");
  const [readUsername, setReadUsername] = useState("");
  const [readPassword, setReadPassword] = useState("");
  const [readConfirmation, setReadConfirmation] = useState("");
  const [backupMode, setBackupMode] = useState<BackupMode | "">("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (adminPassword.length < 12) {
      setError(t("Das Admin-Passwort muss mindestens 12 Zeichen lang sein."));
      return;
    }
    if (!adminConfigured && adminPassword !== adminConfirmation) {
      setError(t("Die Passwörter stimmen nicht überein."));
      return;
    }
    if (!readUsername.trim() || /\s/.test(readUsername.trim())) {
      setError(t("Der Operator-Benutzername darf keine Leerzeichen enthalten."));
      return;
    }
    if (readPassword.length < 12) {
      setError(t("Das Operator-Passwort muss mindestens 12 Zeichen lang sein."));
      return;
    }
    if (readPassword !== readConfirmation) {
      setError(t("Die Operator-Passwörter stimmen nicht überein."));
      return;
    }
    if (!backupMode) {
      setError(t("Wähle eine Backup-Strategie."));
      return;
    }
    setSaving(true);
    setError("");
    try {
      onComplete(
        await api.setupAccess(
          adminPassword,
          readUsername.trim(),
          readPassword,
          backupMode,
        ),
      );
    } catch (reason) {
      const rawMessage =
        reason instanceof Error
          ? reason.message
          : t("Zugänge konnten nicht gespeichert werden.");
      setError(
        rawMessage === "Invalid admin password"
          ? t("Admin-Passwort ist falsch.")
          : rawMessage,
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="setup-shell">
      <section className="setup-card setup-card-wide">
        <div className="setup-language" role="group" aria-label={t("Sprache")}>
          <button
            type="button"
            className={classNames(language === "de" && "active")}
            onClick={() => setLanguage("de")}
          >
            DE
          </button>
          <button
            type="button"
            className={classNames(language === "en" && "active")}
            onClick={() => setLanguage("en")}
          >
            EN
          </button>
        </div>
        <span className="brand-mark setup-brand-mark">
          <ShieldCheck aria-hidden="true" />
        </span>
        <div className="setup-heading">
          <span>{t("Ersteinrichtung")}</span>
          <h1>{t("Zugänge einrichten")}</h1>
          <p>
            {adminConfigured
              ? t(
                  "Bestätige das bestehende Admin-Passwort und ergänze den neuen Operator-Zugang.",
                )
              : t(
                  "Lege den Operator-Zugang für das Dashboard und das separate Admin-Passwort für geschützte Einstellungen fest.",
                )}
          </p>
        </div>
        <form className="setup-form" onSubmit={submit}>
          <label>
            <span>
              {adminConfigured
                ? t("Bestehendes Admin-Passwort")
                : t("Admin-Passwort")}
            </span>
            <input
              type="password"
              autoComplete={adminConfigured ? "current-password" : "new-password"}
              minLength={12}
              maxLength={256}
              required
              value={adminPassword}
              onChange={(event) => setAdminPassword(event.target.value)}
            />
          </label>
          {!adminConfigured && (
            <label>
              <span>{t("Admin-Passwort wiederholen")}</span>
              <input
                type="password"
                autoComplete="new-password"
                minLength={12}
                maxLength={256}
                required
                value={adminConfirmation}
                onChange={(event) => setAdminConfirmation(event.target.value)}
              />
            </label>
          )}
          <div className="setup-divider" />
          <label>
            <span>{t("Operator-Benutzername")}</span>
            <input
              type="text"
              autoComplete="username"
              maxLength={120}
              autoFocus
              required
              value={readUsername}
              onChange={(event) => setReadUsername(event.target.value)}
            />
          </label>
          <label>
            <span>{t("Operator-Passwort")}</span>
            <input
              type="password"
              autoComplete="new-password"
              minLength={12}
              maxLength={256}
              required
              value={readPassword}
              onChange={(event) => setReadPassword(event.target.value)}
            />
          </label>
          <label>
            <span>{t("Operator-Passwort wiederholen")}</span>
            <input
              type="password"
              autoComplete="new-password"
              minLength={12}
              maxLength={256}
              required
              value={readConfirmation}
              onChange={(event) => setReadConfirmation(event.target.value)}
            />
          </label>
          <small>{t("Beide Passwörter benötigen mindestens 12 Zeichen.")}</small>
          <div className="setup-divider" />
          <div className="setup-backup-choice">
            <div>
              <strong>{t("Backup-Strategie")}</strong>
              <small>
                {t(
                  "Diese Entscheidung ist erforderlich und kann später in den Einstellungen geändert werden.",
                )}
              </small>
            </div>
            <BackupModeSelector
              value={backupMode}
              onChange={setBackupMode}
              disabled={saving}
            />
          </div>
          {error && <div className="setup-error">{error}</div>}
          <button
            className="button button-primary setup-submit"
            type="submit"
            disabled={saving || !backupMode}
          >
            <LockKeyhole aria-hidden="true" />
            {saving ? t("Wird gespeichert …") : t("Zugänge speichern")}
          </button>
        </form>
        <div className="settings-note">
          <Info aria-hidden="true" />
          <span>
            {t(
              "Der Operator-Zugang schützt das Dashboard und erlaubt die vorgesehene Alarm- und Host-Triage. Das separate Admin-Passwort schützt Änderungen an globalen Einstellungen.",
            )}
          </span>
        </div>
      </section>
    </div>
  );
}

function BackupStrategySetup({
  language,
  setLanguage,
  onComplete,
}: {
  language: "de" | "en";
  setLanguage: (language: "de" | "en") => void;
  onComplete: (status: AuthStatus) => void;
}) {
  const { t } = useI18n();
  const [mode, setMode] = useState<BackupMode | "">("");
  const [adminPassword, setAdminPassword] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!mode) {
      setError(t("Wähle eine Backup-Strategie."));
      return;
    }
    setSaving(true);
    setError("");
    try {
      onComplete(await api.setupBackup(adminPassword, mode));
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "";
      setError(
        message === "Invalid admin password"
          ? t("Admin-Passwort ist falsch.")
          : message || t("Backup-Strategie konnte nicht gespeichert werden."),
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="setup-shell">
      <section className="setup-card setup-card-wide">
        <div className="setup-language" role="group" aria-label={t("Sprache")}>
          <button
            type="button"
            className={classNames(language === "de" && "active")}
            onClick={() => setLanguage("de")}
          >
            DE
          </button>
          <button
            type="button"
            className={classNames(language === "en" && "active")}
            onClick={() => setLanguage("en")}
          >
            EN
          </button>
        </div>
        <span className="brand-mark setup-brand-mark">
          <HardDriveDownload aria-hidden="true" />
        </span>
        <div className="setup-heading">
          <span>{t("Ersteinrichtung")}</span>
          <h1>{t("Backup-Strategie festlegen")}</h1>
          <p>
            {t(
              "Bestehende Installationen müssen einmalig festlegen, ob DMARC Control selbst sichert oder eine externe Sicherung verantwortlich ist.",
            )}
          </p>
        </div>
        <form className="setup-form" onSubmit={submit}>
          <BackupModeSelector value={mode} onChange={setMode} disabled={saving} />
          <div className="settings-note">
            <Info aria-hidden="true" />
            <span>
              {t(
                "Eine Containersicherung allein genügt nicht. Externe Sicherungen müssen die persistenten data-Verzeichnisse und die Konfiguration anwendungskonsistent erfassen.",
              )}
            </span>
          </div>
          <label>
            <span>{t("Admin-Passwort zur Bestätigung")}</span>
            <input
              type="password"
              autoComplete="current-password"
              required
              maxLength={256}
              value={adminPassword}
              onChange={(event) => setAdminPassword(event.target.value)}
            />
          </label>
          {error && <div className="setup-error">{error}</div>}
          <button
            className="button button-primary setup-submit"
            type="submit"
            disabled={saving || !mode}
          >
            <Save aria-hidden="true" />
            {saving ? t("Wird gespeichert …") : t("Strategie übernehmen")}
          </button>
        </form>
      </section>
    </div>
  );
}

function ReadLogin({
  language,
  setLanguage,
  onComplete,
}: {
  language: "de" | "en";
  setLanguage: (language: "de" | "en") => void;
  onComplete: (status: AuthStatus) => void;
}) {
  const { t } = useI18n();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      onComplete(await api.loginRead(username.trim(), password));
    } catch (reason) {
      const rawMessage =
        reason instanceof Error ? reason.message : t("Anmeldung fehlgeschlagen.");
      setError(
        (rawMessage === "Invalid read credentials"
          || rawMessage === "Invalid operator credentials")
          ? t("Benutzername oder Passwort ist falsch.")
          : rawMessage,
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="setup-shell">
      <section className="setup-card">
        <div className="setup-language" role="group" aria-label={t("Sprache")}>
          <button
            type="button"
            className={classNames(language === "de" && "active")}
            onClick={() => setLanguage("de")}
          >
            DE
          </button>
          <button
            type="button"
            className={classNames(language === "en" && "active")}
            onClick={() => setLanguage("en")}
          >
            EN
          </button>
        </div>
        <span className="brand-mark setup-brand-mark">
          <ShieldCheck aria-hidden="true" />
        </span>
        <div className="setup-heading">
          <span>{t("Geschützter Zugriff")}</span>
          <h1>{t("Bei DMARC Control anmelden")}</h1>
          <p>{t("Melde dich mit dem beim Setup definierten Operator-Zugang an.")}</p>
        </div>
        <form className="setup-form" onSubmit={submit}>
          <label>
            <span>{t("Benutzername")}</span>
            <input
              type="text"
              autoComplete="username"
              maxLength={120}
              autoFocus
              required
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
          </label>
          <label>
            <span>{t("Passwort")}</span>
            <input
              type="password"
              autoComplete="current-password"
              maxLength={256}
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          {error && <div className="setup-error">{error}</div>}
          <button
            className="button button-primary setup-submit"
            type="submit"
            disabled={busy}
          >
            <LockKeyhole aria-hidden="true" />
            {busy ? t("Anmeldung läuft …") : t("Anmelden")}
          </button>
        </form>
      </section>
    </div>
  );
}

function DashboardApp({
  auth,
  setAuth,
}: {
  auth: AuthStatus;
  setAuth: (status: AuthStatus) => void;
}) {
  const { t } = useI18n();
  const [readLogoutBusy, setReadLogoutBusy] = useState(false);
  const { location, go } = useInvestigationNavigation();
  const { request } = useUnsavedChanges();
  const { view, domain, days, alert: targetAlertId, host: targetHostIp, fromAlert: originAlertId } = location;
  const [domains, setDomains] = useState<DomainItem[]>([]);
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
  ) => {
    const updated = await api.updateAppearance(profile, color);
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

  const [domainRevision, setDomainRevision] = useState(0);
  const loadDomains = useCallback(() => setDomainRevision((value) => value + 1), []);
  useEffect(() => {
    const controller = new AbortController();
    setDomainError("");
    api.domains(controller.signal)
      .then((items) => { if (!controller.signal.aborted) setDomains(items); })
      .catch((error: Error) => { if (!controller.signal.aborted) setDomainError(error.message); });
    return () => controller.abort();
  }, [domainRevision, refreshKey]);

  const navigate = (nextView: View) => go({
    view: nextView, domain, days,
    alert: nextView === "alerts" ? targetAlertId : undefined,
    host: nextView === "hosts" ? targetHostIp : undefined,
    fromAlert: nextView === "hosts" ? originAlertId : undefined,
    fromDomain: nextView === "hosts" ? location.fromDomain : undefined,
    fromDays: nextView === "hosts" ? location.fromDays : undefined,
  });

  const investigateAlertHost = (alert: Alert) => {
    if (!alert.source_ip) return;
    go({ view: "hosts", domain: validDomain(alert.domain), days, host: alert.source_ip,
      fromAlert: alert.id, fromDomain: domain, fromDays: days });
  };

  const returnToAlert = () => {
    if (!originAlertId) return;
    go({ view: "alerts", domain: location.fromDomain ?? domain,
      days: location.fromDays ?? days, alert: originAlertId });
  };

  const logoutRead = async () => {
    setReadLogoutBusy(true);
    try {
      setAuth(await api.logoutRead());
    } finally {
      setReadLogoutBusy(false);
    }
  };

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
        <div className="header-actions">
          <div className="health-label">
            <span className="health-dot" />
            {t("Live aus OpenSearch")}
          </div>
          <span className="read-user-label">
            {t("Angemeldet als {username}", {
              username: auth.read_username ?? "Operator",
            })}
          </span>
          <button
            className="button button-ghost read-logout"
            type="button"
            disabled={readLogoutBusy}
            onClick={() => request(() => void logoutRead())}
          >
            <LogOut aria-hidden="true" />
            {t("Abmelden")}
          </button>
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
              onClick={() => navigate(item.id)}
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
          onClick={() => navigate("settings")}
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
              <select value={domain} onChange={(event) => go({ ...location, domain: event.target.value })}>
                <option value="*">{t("Alle Domains")}</option>
                {domain !== "*" && !domains.some((item) => item.domain === domain) && <option value={domain}>{domain}</option>}
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
                onChange={(event) => go({ ...location, days: Number(event.target.value) })}
              >
                <option value={7}>{t("Letzte 7 Tage")}</option>
                <option value={30}>{t("Letzte 30 Tage")}</option>
                <option value={90}>{t("Letzte 90 Tage")}</option>
                <option value={365}>{t("Letzte 12 Monate")}</option>
                {![7, 30, 90, 365].includes(days) && <option value={days}>{t("{days} Tage", { days })}</option>}
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
            openAlerts={() => navigate("alerts")}
            openHosts={(ip, sourceDomain) => go({ view: "hosts", domain: validDomain(sourceDomain ?? domain), days, host: ip })}
          />
        )}
        {view === "hosts" && (
          <HostsView
            domain={domain}
            days={days}
            refreshKey={refreshKey}
            targetHostIp={targetHostIp}
            originAlertId={originAlertId}
            selectHost={(ip) => go({ ...location, host: ip })}
            clearTargetHost={() => go({ view: "hosts", domain, days })}
            returnToAlert={returnToAlert}
          />
        )}
        {view === "alerts" && (
          <AlertsView
            adminAuthenticated={Boolean(auth?.authenticated)}
            domain={domain}
            days={days}
            refreshKey={refreshKey}
            targetAlertId={targetAlertId}
            investigateHost={investigateAlertHost}
          />
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
            auth={auth}
            setAuth={setAuth}
            updateColor={updateBrandColor}
            saveCustomColor={saveCustomColor}
            resetLocalBrand={resetLocalBrand}
            updateGlobalAppearance={updateGlobalAppearance}
            onDomainsChanged={loadDomains}
          />
        )}
      </main>

      <footer>
        <span>
          DMARC Control · {t("Basiert auf")} {" "}
          <a
            href="https://github.com/domainaware/parsedmarc"
            target="_blank"
            rel="noreferrer"
          >
            parsedmarc
          </a>
        </span>
        <span>
          {t(
            "OpenSearch ist ausschließlich über die kontrollierte API erreichbar.",
          )}
        </span>
      </footer>
    </div>
  );
}

interface MailboxFormState {
  provider: MailboxProvider;
  tenant_id: string;
  client_id: string;
  mailbox: string;
  host: string;
  port: number;
  user: string;
  reports_folder: string;
  archive_folder: string;
}

const defaultMailboxForm = (): MailboxFormState => ({
  provider: "msgraph",
  tenant_id: "",
  client_id: "",
  mailbox: "",
  host: "",
  port: 993,
  user: "",
  reports_folder: "Inbox/DMARC",
  archive_folder: "Inbox/DMARC/Processed",
});

function MailboxConnectionSettings({
  auth,
  setAuth,
  onStateChange,
}: {
  auth: AuthStatus;
  setAuth: (status: AuthStatus) => void;
  onStateChange: (state: MailboxConnectionState | null) => void;
}) {
  const { t, formatDate } = useI18n();
  const [connection, setConnection] =
    useState<MailboxConnectionState | null>(null);
  const [form, setForm] = useState<MailboxFormState>(defaultMailboxForm);
  const [clientSecret, setClientSecret] = useState("");
  const [imapPassword, setImapPassword] = useState("");
  const [dirty, setDirty] = useState(false);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<
    "save" | "test" | "activate" | null
  >(null);
  const [feedback, setFeedback] = useState("");
  const [feedbackTone, setFeedbackTone] = useState<
    "success" | "critical" | "info"
  >("info");
  const [confirmActivation, setConfirmActivation] = useState(false);
  const publishConnection = useCallback(
    (next: MailboxConnectionState | null) => {
      setConnection(next);
      onStateChange(next);
    },
    [onStateChange],
  );

  const translateError = useCallback(
    (rawMessage: string) => {
      const messages: Record<string, string> = {
        "Admin login required": t(
          "Die Admin-Sitzung ist abgelaufen. Bitte erneut anmelden.",
        ),
        "Tenant ID must be a UUID": t(
          "Die Tenant-ID muss eine gültige UUID sein.",
        ),
        "Client ID must be a UUID": t(
          "Die Client-ID muss eine gültige UUID sein.",
        ),
        "Mailbox must be an email address": t(
          "Das Postfach muss eine gültige E-Mail-Adresse sein.",
        ),
        "Client secret is required": t(
          "Ein Client Secret muss hinterlegt werden.",
        ),
        "IMAP password is required": t(
          "Ein IMAP-Passwort muss hinterlegt werden.",
        ),
        "Reports and archive folders must be different": t(
          "Eingangs- und Archivordner müssen unterschiedlich sein.",
        ),
      };
      return messages[rawMessage] ?? rawMessage;
    },
    [t],
  );

  const hydrate = useCallback((next: MailboxConnectionState) => {
    publishConnection(next);
    const draft = next.draft;
    if (!draft) {
      setForm(defaultMailboxForm());
      setClientSecret("");
      setImapPassword("");
      setDirty(false);
      return;
    }
    const values = draft.settings;
    setForm({
      provider: draft.provider,
      tenant_id: values.tenant_id ?? "",
      client_id: values.client_id ?? "",
      mailbox: values.mailbox ?? "",
      host: values.host ?? "",
      port: values.port ?? 993,
      user: values.user ?? "",
      reports_folder: values.reports_folder,
      archive_folder: values.archive_folder,
    });
    setClientSecret("");
    setImapPassword("");
    setDirty(false);
  }, [publishConnection]);

  const load = useCallback(
    async (hydrateValues = false) => {
      if (!auth.authenticated) return;
      setLoading(true);
      try {
        const next = await api.mailboxSettings();
        if (hydrateValues) hydrate(next);
        else publishConnection(next);
      } catch (reason) {
        const rawMessage =
          reason instanceof Error
            ? reason.message
            : t("Anbindung konnte nicht geladen werden.");
        if (rawMessage === "Admin login required") {
          setAuth({ ...auth, authenticated: false });
        }
        setFeedbackTone("critical");
        setFeedback(translateError(rawMessage));
      } finally {
        setLoading(false);
      }
    },
    [auth, hydrate, publishConnection, setAuth, t, translateError],
  );

  useEffect(() => {
    if (auth.authenticated) {
      load(true);
    } else {
      publishConnection(null);
    }
  }, [auth.authenticated, load, publishConnection]);

  useEffect(() => {
    if (!auth.authenticated) return;
    const interval = window.setInterval(() => {
      api
        .mailboxSettings()
        .then(publishConnection)
        .catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(interval);
  }, [auth.authenticated, publishConnection]);

  const updateField = (
    field: keyof MailboxFormState,
    value: string | number,
  ) => {
    setForm((current) => ({ ...current, [field]: value }));
    setDirty(true);
    setConfirmActivation(false);
  };

  const selectProvider = (provider: MailboxProvider) => {
    setForm((current) => ({
      ...current,
      provider,
      reports_folder:
        provider === "msgraph" ? "Inbox/DMARC" : "INBOX",
      archive_folder:
        provider === "msgraph" ? "Inbox/DMARC/Processed" : "Archive",
    }));
    setDirty(true);
    setConfirmActivation(false);
    setFeedback("");
  };

  const save = async (event: FormEvent) => {
    event.preventDefault();
    const update: MailboxConnectionUpdate = {
      provider: form.provider,
      reports_folder: form.reports_folder,
      archive_folder: form.archive_folder,
      ...(form.provider === "msgraph"
        ? {
            tenant_id: form.tenant_id,
            client_id: form.client_id,
            client_secret: clientSecret || undefined,
            mailbox: form.mailbox,
          }
        : {
            host: form.host,
            port: form.port,
            user: form.user,
            password: imapPassword || undefined,
          }),
    };
    setBusy("save");
    setFeedback("");
    try {
      const saved = await api.saveMailboxSettings(update);
      hydrate(saved);
      setFeedbackTone("success");
      setFeedback(
        t(
          "Verbindungsentwurf gespeichert. Führe jetzt den read-only Test aus.",
        ),
      );
    } catch (reason) {
      const rawMessage =
        reason instanceof Error ? reason.message : t("Speichern fehlgeschlagen.");
      if (rawMessage === "Admin login required") {
        setAuth({ ...auth, authenticated: false });
      }
      setFeedbackTone("critical");
      setFeedback(translateError(rawMessage));
    } finally {
      setBusy(null);
    }
  };

  const testConnection = async () => {
    setBusy("test");
    setFeedback("");
    try {
      const tested = await api.testMailboxSettings();
      publishConnection(tested);
      const successful = tested.test_status === "success";
      setFeedbackTone(successful ? "success" : "critical");
      setFeedback(
        tested.test_message
          ? t(tested.test_message)
          : successful
            ? t("Verbindungstest erfolgreich.")
            : t("Verbindungstest fehlgeschlagen."),
      );
    } catch (reason) {
      const rawMessage =
        reason instanceof Error
          ? reason.message
          : t("Verbindungstest fehlgeschlagen.");
      if (rawMessage === "Admin login required") {
        setAuth({ ...auth, authenticated: false });
      }
      setFeedbackTone("critical");
      setFeedback(translateError(rawMessage));
    } finally {
      setBusy(null);
    }
  };

  const activate = async () => {
    setBusy("activate");
    setFeedback("");
    try {
      const activated = await api.activateMailboxSettings();
      publishConnection(activated);
      setConfirmActivation(false);
      setFeedbackTone("success");
      setFeedback(
        t(
          "Anbindung aktiviert. Der einzelne Parser-Prozess übernimmt die neue Konfiguration.",
        ),
      );
      window.setTimeout(() => load(false), 6000);
    } catch (reason) {
      const rawMessage =
        reason instanceof Error
          ? reason.message
          : t("Aktivierung fehlgeschlagen.");
      if (rawMessage === "Admin login required") {
        setAuth({ ...auth, authenticated: false });
      }
      setFeedbackTone("critical");
      setFeedback(translateError(rawMessage));
    } finally {
      setBusy(null);
    }
  };

  const testedCurrent =
    connection?.test_status === "success" &&
    connection.tested_revision === connection.draft_revision;
  const currentIsActive =
    connection?.active_revision !== null &&
    connection?.active_revision === connection?.draft_revision;
  const parserManaged =
    connection?.parser?.mode === "managed" &&
    connection.parser.state === "running" &&
    connection.parser.revision === connection.active_revision;
  const statusTone =
    connection?.parser?.state === "error"
      ? "critical"
      : parserManaged
        ? "success"
        : testedCurrent
          ? "info"
          : "neutral";
  const statusLabel =
    connection?.parser?.state === "error"
      ? t("Parserfehler")
      : parserManaged
        ? t("Verwaltete Anbindung aktiv")
        : currentIsActive
          ? t("Parser übernimmt Konfiguration")
          : testedCurrent
            ? t("Bereit zur Aktivierung")
            : connection?.configured
              ? t("Entwurf gespeichert")
              : connection?.parser?.mode === "legacy"
                ? t("Bestehende Konfiguration aktiv")
                : t("Nicht eingerichtet");

  return (
    <section className="surface connection-settings">
      <div className="settings-title connection-title">
        <span className="settings-icon">
          <PlugZap aria-hidden="true" />
        </span>
        <div>
          <h3>{t("Anbindung")}</h3>
          <p>
            {t(
              "Microsoft 365 oder IMAP verbinden, ohne eine Docker-Konfigurationsdatei manuell zu bearbeiten.",
            )}
          </p>
        </div>
        <StatusPill tone={statusTone}>{statusLabel}</StatusPill>
      </div>

      {!auth.authenticated ? (
        <div className="connection-locked">
          <LockKeyhole aria-hidden="true" />
          <div>
            <strong>{t("Admin-Anmeldung erforderlich")}</strong>
            <small>
              {t(
                "Verbindungsdaten und Tests sind ausschließlich für angemeldete Administratoren verfügbar.",
              )}
            </small>
          </div>
        </div>
      ) : loading && !connection ? (
        <LoadingState label={t("Anbindung wird geladen")} />
      ) : (
        <>
          <div className="connection-status-grid">
            <div>
              <span>{t("Aktiver Modus")}</span>
              <strong>
                {connection?.parser?.mode === "managed"
                  ? t("GUI-verwaltet")
                  : t("Bestehende Konfiguration")}
              </strong>
            </div>
            <div>
              <span>parsedmarc</span>
              <strong>{connection?.parser?.version ?? "10.4.0"}</strong>
            </div>
            <div>
              <span>{t("Letzter Verbindungstest")}</span>
              <strong>
                {connection?.tested_at
                  ? formatDate(connection.tested_at, true)
                  : t("Noch nicht durchgeführt")}
              </strong>
            </div>
          </div>

          <div
            className="connection-provider-switch"
            role="group"
            aria-label={t("Verbindungsart")}
          >
            <button
              type="button"
              className={classNames(form.provider === "msgraph" && "active")}
              aria-pressed={form.provider === "msgraph"}
              onClick={() => selectProvider("msgraph")}
            >
              <Cloud aria-hidden="true" />
              <span>
                <strong>Microsoft 365</strong>
                <small>{t("Graph API · App-Registrierung")}</small>
              </span>
            </button>
            <button
              type="button"
              className={classNames(form.provider === "imap" && "active")}
              aria-pressed={form.provider === "imap"}
              onClick={() => selectProvider("imap")}
            >
              <Mail aria-hidden="true" />
              <span>
                <strong>IMAP</strong>
                <small>{t("TLS · Benutzer oder App-Passwort")}</small>
              </span>
            </button>
          </div>

          <form className="connection-form" onSubmit={save}>
            {form.provider === "msgraph" ? (
              <div className="connection-fields graph-fields">
                <label>
                  <span>{t("Tenant-ID")}</span>
                  <input
                    type="text"
                    autoComplete="off"
                    required
                    value={form.tenant_id}
                    placeholder="00000000-0000-0000-0000-000000000000"
                    onChange={(event) =>
                      updateField("tenant_id", event.target.value)
                    }
                  />
                </label>
                <label>
                  <span>{t("Client-ID")}</span>
                  <input
                    type="text"
                    autoComplete="off"
                    required
                    value={form.client_id}
                    placeholder="00000000-0000-0000-0000-000000000000"
                    onChange={(event) =>
                      updateField("client_id", event.target.value)
                    }
                  />
                </label>
                <label>
                  <span>{t("Client Secret")}</span>
                  <input
                    type="password"
                    autoComplete="new-password"
                    required={
                      !(
                        connection?.draft?.provider === "msgraph" &&
                        connection.draft.secret_configured
                      )
                    }
                    value={clientSecret}
                    placeholder={
                      connection?.draft?.provider === "msgraph" &&
                      connection.draft.secret_configured
                        ? t("Secret hinterlegt · leer lassen zum Beibehalten")
                        : t("Secret-Wert, nicht die Secret-ID")
                    }
                    onChange={(event) => {
                      setClientSecret(event.target.value);
                      setDirty(true);
                    }}
                  />
                </label>
                <label>
                  <span>{t("DMARC-Postfach")}</span>
                  <input
                    type="email"
                    autoComplete="off"
                    required
                    value={form.mailbox}
                    placeholder="dmarc-reports@example.com"
                    onChange={(event) =>
                      updateField("mailbox", event.target.value)
                    }
                  />
                </label>
              </div>
            ) : (
              <div className="connection-fields imap-fields">
                <label>
                  <span>{t("IMAP-Server")}</span>
                  <input
                    type="text"
                    autoComplete="off"
                    required
                    value={form.host}
                    placeholder="imap.example.com"
                    onChange={(event) =>
                      updateField("host", event.target.value)
                    }
                  />
                </label>
                <label>
                  <span>{t("Port")}</span>
                  <input
                    type="number"
                    min={1}
                    max={65535}
                    required
                    value={form.port}
                    onChange={(event) =>
                      updateField("port", Number(event.target.value))
                    }
                  />
                </label>
                <label>
                  <span>{t("Benutzername")}</span>
                  <input
                    type="text"
                    autoComplete="username"
                    required
                    value={form.user}
                    placeholder="dmarc@example.com"
                    onChange={(event) =>
                      updateField("user", event.target.value)
                    }
                  />
                </label>
                <label>
                  <span>{t("Passwort / App-Passwort")}</span>
                  <input
                    type="password"
                    autoComplete="new-password"
                    required={
                      !(
                        connection?.draft?.provider === "imap" &&
                        connection.draft.secret_configured
                      )
                    }
                    value={imapPassword}
                    placeholder={
                      connection?.draft?.provider === "imap" &&
                      connection.draft.secret_configured
                        ? t("Passwort hinterlegt · leer lassen zum Beibehalten")
                        : t("IMAP- oder App-Passwort")
                    }
                    onChange={(event) => {
                      setImapPassword(event.target.value);
                      setDirty(true);
                    }}
                  />
                </label>
              </div>
            )}

            <div className="connection-fields folder-fields">
              <label>
                <span>{t("Eingangsordner")}</span>
                <input
                  type="text"
                  required
                  value={form.reports_folder}
                  onChange={(event) =>
                    updateField("reports_folder", event.target.value)
                  }
                />
              </label>
              <label>
                <span>{t("Archivordner")}</span>
                <input
                  type="text"
                  required
                  value={form.archive_folder}
                  onChange={(event) =>
                    updateField("archive_folder", event.target.value)
                  }
                />
              </label>
            </div>

            {form.provider === "msgraph" ? (
              <div className="settings-note">
                <ShieldCheck aria-hidden="true" />
                <span>
                  {t(
                    "Erforderlich: Application Mail.ReadWrite, begrenzt auf dieses Postfach. Die Anwendung erstellt keine Entra-App.",
                  )}
                </span>
              </div>
            ) : (
              <div className="settings-note">
                <ShieldCheck aria-hidden="true" />
                <span>
                  {t(
                    "TLS und Zertifikatsprüfung sind immer aktiv. OAuth-only-Anbieter benötigen einen eigenen API-Adapter.",
                  )}
                </span>
              </div>
            )}

            <div className="connection-actions">
              <button
                className="button button-primary"
                type="submit"
                disabled={busy !== null}
              >
                <Save aria-hidden="true" />
                {busy === "save"
                  ? t("Wird gespeichert …")
                  : t("Entwurf speichern")}
              </button>
              <button
                className="button button-secondary"
                type="button"
                disabled={
                  busy !== null ||
                  dirty ||
                  !connection?.draft_revision
                }
                title={
                  dirty
                    ? t("Speichere Änderungen vor dem Verbindungstest.")
                    : undefined
                }
                onClick={testConnection}
              >
                <RefreshCw aria-hidden="true" />
                {busy === "test"
                  ? t("Verbindung wird geprüft …")
                  : t("Verbindung testen")}
              </button>
              <button
                className="button button-ghost"
                type="button"
                disabled={
                  busy !== null ||
                  !testedCurrent ||
                  currentIsActive ||
                  dirty
                }
                onClick={() => setConfirmActivation(true)}
              >
                <CheckCircle2 aria-hidden="true" />
                {t("Aktivieren")}
              </button>
            </div>
          </form>

          <div className="connection-readonly-note">
            <EyeOff aria-hidden="true" />
            <span>
              {t(
                "Der Test meldet sich an und prüft die Ordner ausschließlich lesend. Er lädt, verarbeitet, verschiebt und löscht keine Nachrichten.",
              )}
            </span>
          </div>

          {confirmActivation && (
            <div className="activation-confirmation">
              <TriangleAlert aria-hidden="true" />
              <div>
                <strong>{t("Neue Anbindung jetzt aktivieren?")}</strong>
                <p>
                  {t(
                    "Der bestehende einzelne Parser-Prozess wird kurz gestoppt und mit dem geprüften Entwurf neu gestartet. OpenSearch läuft weiter.",
                  )}
                </p>
                <div>
                  <button
                    className="button button-primary"
                    type="button"
                    disabled={busy !== null}
                    onClick={activate}
                  >
                    {busy === "activate"
                      ? t("Wird aktiviert …")
                      : t("Geprüfte Anbindung aktivieren")}
                  </button>
                  <button
                    className="button button-ghost"
                    type="button"
                    disabled={busy !== null}
                    onClick={() => setConfirmActivation(false)}
                  >
                    {t("Abbrechen")}
                  </button>
                </div>
              </div>
            </div>
          )}

          {connection?.parser?.message && (
            <div className="inline-warning">
              <TriangleAlert aria-hidden="true" />
              {connection.parser.message}
            </div>
          )}
          {feedback && (
            <div className="settings-feedback" aria-live="polite">
              <StatusPill tone={feedbackTone}>{feedback}</StatusPill>
            </div>
          )}
        </>
      )}
    </section>
  );
}

const DEFAULT_NOTIFICATION_CASES: NotificationCase[] = [
  "new-host-fail",
  "host-degradation",
  "host-fail",
  "dynamic-ip-fail",
  "stale-reports",
];

const NOTIFICATION_CASE_OPTIONS: Array<{
  value: NotificationCase;
  label: string;
  description: string;
}> = [
  {
    value: "new-host-fail",
    label: "Neuer Host mit DMARC-Fail",
    description: "Erstmals beobachtete Quelle mit echtem DMARC-Fail.",
  },
  {
    value: "host-degradation",
    label: "Verschlechterung eines Hosts",
    description: "Zuvor unauffälliger Host liefert neu DMARC-Fails.",
  },
  {
    value: "host-fail",
    label: "DMARC-Fehlerquelle",
    description: "Bekannte Quelle mit mindestens einem echten DMARC-Fail.",
  },
  {
    value: "dynamic-ip-fail",
    label: "Dynamischer IP-Bereich",
    description: "DMARC-Fail aus einem erkannten Endkunden- oder Zugangsnetz.",
  },
  {
    value: "new-source-ip",
    label: "Neue Source-IP",
    description: "Neue Quelle, auch wenn DMARC noch bestanden wurde.",
  },
  {
    value: "compensated-alignment",
    label: "Kompensiertes Alignment",
    description: "SPF oder DKIM nicht aligned, finales DMARC aber bestanden.",
  },
  {
    value: "stale-reports",
    label: "Ausbleibende Reports",
    description: "Keine neuen DMARC-Reports nach berücksichtigter Verzögerung.",
  },
];

function defaultNotificationForm(): NotificationSettingsUpdate {
  return {
    enabled: false,
    transport: "smtp",
    recipients: [],
    sender: "",
    language: "de",
    dashboard_url: "",
    cases: DEFAULT_NOTIFICATION_CASES,
    smtp: {
      host: "",
      port: 587,
      security: "starttls",
      username: "",
    },
    graph: {
      reuse_mailbox_connection: true,
      tenant_id: "",
      client_id: "",
    },
  };
}

function NotificationSettingsPanel({
  auth,
  setAuth,
}: {
  auth: AuthStatus;
  setAuth: (status: AuthStatus) => void;
}) {
  const { t, formatDate } = useI18n();
  const [settingsState, setSettingsState] =
    useState<NotificationSettings | null>(null);
  const [statusState, setStatusState] = useState<
    Pick<NotificationSettings, "configured" | "enabled"> | null
  >(null);
  const [form, setForm] = useState<NotificationSettingsUpdate>(
    defaultNotificationForm,
  );
  const [recipientText, setRecipientText] = useState("");
  const [smtpPassword, setSmtpPassword] = useState("");
  const [graphSecret, setGraphSecret] = useState("");
  const [dirty, setDirty] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<"save" | "test" | null>(null);
  const [feedback, setFeedback] = useState("");
  const [feedbackTone, setFeedbackTone] = useState<
    "success" | "critical" | "info"
  >("info");

  const handleError = useCallback(
    (reason: unknown, fallback: string) => {
      const rawMessage =
        reason instanceof Error ? reason.message : fallback;
      if (rawMessage === "Admin login required") {
        setAuth({ ...auth, authenticated: false });
        return t("Die Admin-Sitzung ist abgelaufen. Bitte erneut anmelden.");
      }
      const messages: Record<string, string> = {
        "SMTP host is invalid": t("Der SMTP-Server ist ungültig."),
        "SMTP password is required when a username is set": t(
          "Bei gesetztem SMTP-Benutzernamen ist ein Passwort erforderlich.",
        ),
        "Graph tenant ID must be a UUID": t(
          "Die Graph Tenant-ID muss eine gültige UUID sein.",
        ),
        "Graph client ID must be a UUID": t(
          "Die Graph Client-ID muss eine gültige UUID sein.",
        ),
        "Graph client secret is required": t(
          "Ein Graph Client Secret muss hinterlegt werden.",
        ),
        "No Microsoft Graph mailbox connection is available for reuse": t(
          "Es ist keine Microsoft-Graph-Postfachanbindung zur Wiederverwendung vorhanden.",
        ),
        "Dashboard URL must be an HTTP or HTTPS URL": t(
          "Die Dashboard-URL muss mit http:// oder https:// beginnen.",
        ),
      };
      return messages[rawMessage] ?? rawMessage;
    },
    [auth, setAuth, t],
  );

  const hydrate = useCallback((next: NotificationSettings) => {
    setSettingsState(next);
    setStatusState({ configured: next.configured, enabled: next.enabled });
    setForm({
      enabled: next.enabled,
      transport: next.transport,
      recipients: next.recipients,
      sender: next.sender,
      language: next.language,
      dashboard_url: next.dashboard_url,
      cases: next.cases,
      smtp: {
        host: next.smtp.host,
        port: next.smtp.port,
        security: next.smtp.security,
        username: next.smtp.username,
      },
      graph: {
        reuse_mailbox_connection: next.graph.reuse_mailbox_connection,
        tenant_id: next.graph.tenant_id,
        client_id: next.graph.client_id,
      },
    });
    setRecipientText(next.recipients.join("\n"));
    setSmtpPassword("");
    setGraphSecret("");
    setDirty(false);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setFeedback("");
    try {
      if (auth.authenticated) {
        hydrate(await api.notificationSettings());
      } else {
        setSettingsState(null);
        setStatusState(await api.notificationStatus());
      }
    } catch (reason) {
      setFeedbackTone("critical");
      setFeedback(
        handleError(
          reason,
          t("Benachrichtigungseinstellungen konnten nicht geladen werden."),
        ),
      );
    } finally {
      setLoading(false);
    }
  }, [auth.authenticated, handleError, hydrate, t]);

  useEffect(() => {
    load();
  }, [load]);

  const updateForm = (
    updater: (current: NotificationSettingsUpdate) => NotificationSettingsUpdate,
  ) => {
    setForm(updater);
    setDirty(true);
    setFeedback("");
  };

  const toggleCase = (notificationCase: NotificationCase) => {
    updateForm((current) => ({
      ...current,
      cases: current.cases.includes(notificationCase)
        ? current.cases.filter((item) => item !== notificationCase)
        : [...current.cases, notificationCase],
    }));
  };

  const save = async (event: FormEvent) => {
    event.preventDefault();
    const recipients = recipientText
      .split(/[\n,;]+/)
      .map((item) => item.trim())
      .filter(Boolean);
    if (!recipients.length) {
      setFeedbackTone("critical");
      setFeedback(t("Mindestens ein Empfänger ist erforderlich."));
      return;
    }
    if (!form.cases.length) {
      setFeedbackTone("critical");
      setFeedback(t("Wähle mindestens einen Benachrichtigungsfall."));
      return;
    }
    const update: NotificationSettingsUpdate = {
      ...form,
      recipients,
      smtp: {
        ...form.smtp,
        password: smtpPassword || undefined,
      },
      graph: {
        ...form.graph,
        client_secret: graphSecret || undefined,
      },
    };
    setBusy("save");
    setFeedback("");
    try {
      hydrate(await api.saveNotificationSettings(update));
      setFeedbackTone("success");
      setFeedback(t("Benachrichtigungseinstellungen wurden gespeichert."));
    } catch (reason) {
      setFeedbackTone("critical");
      setFeedback(handleError(reason, t("Speichern fehlgeschlagen.")));
    } finally {
      setBusy(null);
    }
  };

  const sendTest = async () => {
    setBusy("test");
    setFeedback("");
    try {
      const tested = await api.testNotificationSettings();
      setSettingsState(tested);
      const success = tested.test_status === "success";
      setFeedbackTone(success ? "success" : "critical");
      setFeedback(
        success
          ? t("Test-E-Mail wurde erfolgreich versendet.")
          : tested.test_message
            ? handleError(
                new Error(tested.test_message),
                t("Test-E-Mail konnte nicht versendet werden."),
              )
            : t("Test-E-Mail konnte nicht versendet werden."),
      );
    } catch (reason) {
      setFeedbackTone("critical");
      setFeedback(
        handleError(reason, t("Test-E-Mail konnte nicht versendet werden.")),
      );
    } finally {
      setBusy(null);
    }
  };

  const statusTone = !statusState
    ? ("neutral" as const)
    : !statusState.configured
      ? ("neutral" as const)
      : statusState.enabled
        ? ("success" as const)
        : ("info" as const);
  const statusLabel = loading && !statusState
    ? t("Benachrichtigungen werden geladen")
    : !statusState
      ? t("Status nicht verfügbar")
      : !statusState.configured
        ? t("Nicht eingerichtet")
        : statusState.enabled
          ? t("E-Mail-Alerting aktiv")
          : t("E-Mail-Alerting pausiert");

  return (
    <section className="surface notification-settings">
      <div className="settings-title connection-title">
        <span className="settings-icon">
          <Bell aria-hidden="true" />
        </span>
        <div>
          <h3>{t("E-Mail-Benachrichtigungen")}</h3>
          <p>
            {t(
              "Kritische Fälle und Hinweise als strukturierte HTML-E-Mail über SMTP oder Microsoft Graph versenden.",
            )}
          </p>
        </div>
        <StatusPill tone={statusTone}>{statusLabel}</StatusPill>
      </div>

      <AlertEvaluationMonitor refreshKey={`${settingsState?.updated_at ?? ""}:${auth.authenticated}`} />
      {!auth.authenticated ? (
        <div className="connection-locked">
          <LockKeyhole aria-hidden="true" />
          <div>
            <strong>{t("Admin-Anmeldung erforderlich")}</strong>
            <small>
              {t(
                "Versandwege, Empfänger und auslösende Fälle sind ausschließlich für Administratoren sichtbar.",
              )}
            </small>
          </div>
        </div>
      ) : loading && !settingsState ? (
        <LoadingState label={t("Benachrichtigungen werden geladen")} />
      ) : (
        <form className="notification-form" onSubmit={save}>
          <label className="notification-enable">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(event) =>
                updateForm((current) => ({
                  ...current,
                  enabled: event.target.checked,
                }))
              }
            />
            <span>
              <strong>{t("Automatischen E-Mail-Versand aktivieren")}</strong>
              <small>
                {t(
                  "Neue offene Ereignisse werden einmalig versendet und über Container-Neustarts hinweg dedupliziert.",
                )}
              </small>
            </span>
          </label>

          <div
            className="connection-provider-switch"
            role="group"
            aria-label={t("Versandweg")}
          >
            <button
              type="button"
              className={classNames(form.transport === "smtp" && "active")}
              aria-pressed={form.transport === "smtp"}
              onClick={() =>
                updateForm((current) => ({
                  ...current,
                  transport: "smtp",
                }))
              }
            >
              <Mail aria-hidden="true" />
              <span>
                <strong>SMTP</strong>
                <small>{t("STARTTLS, TLS oder internes Relay")}</small>
              </span>
            </button>
            <button
              type="button"
              className={classNames(form.transport === "msgraph" && "active")}
              aria-pressed={form.transport === "msgraph"}
              onClick={() =>
                updateForm((current) => ({
                  ...current,
                  transport: "msgraph",
                }))
              }
            >
              <Cloud aria-hidden="true" />
              <span>
                <strong>Microsoft Graph</strong>
                <small>{t("Microsoft 365 · App-only Mail.Send")}</small>
              </span>
            </button>
          </div>

          <div className="notification-fields notification-addresses">
            <label>
              <span>{t("Empfänger")}</span>
              <textarea
                required
                rows={3}
                value={recipientText}
                placeholder={"security@example.com\nsoc@example.com"}
                onChange={(event) => {
                  setRecipientText(event.target.value);
                  setDirty(true);
                }}
              />
              <small>{t("Eine Adresse pro Zeile; maximal 20 Empfänger.")}</small>
            </label>
            <div>
              <label>
                <span>{t("Absender")}</span>
                <input
                  type="email"
                  required
                  value={form.sender}
                  placeholder="dmarc-alerts@example.com"
                  onChange={(event) =>
                    updateForm((current) => ({
                      ...current,
                      sender: event.target.value,
                    }))
                  }
                />
              </label>
              <label>
                <span>{t("Sprache der E-Mail")}</span>
                <select
                  value={form.language}
                  onChange={(event) =>
                    updateForm((current) => ({
                      ...current,
                      language: event.target.value as "de" | "en",
                    }))
                  }
                >
                  <option value="de">Deutsch</option>
                  <option value="en">English</option>
                </select>
              </label>
            </div>
          </div>

          <label>
            <span>{t("Öffentliche Dashboard-URL")}</span>
            <input
              type="url"
              value={form.dashboard_url}
              placeholder="https://dmarc.example.com"
              onChange={(event) =>
                updateForm((current) => ({
                  ...current,
                  dashboard_url: event.target.value,
                }))
              }
            />
            <small>
              {t(
                "Optional. Wird für den direkten Link zur Warnungszentrale verwendet.",
              )}
            </small>
          </label>

          {form.transport === "smtp" ? (
            <div className="notification-transport-fields">
              <div className="notification-fields smtp-notification-fields">
                <label>
                  <span>{t("SMTP-Server")}</span>
                  <input
                    type="text"
                    required
                    value={form.smtp.host}
                    placeholder="smtp.example.com"
                    onChange={(event) =>
                      updateForm((current) => ({
                        ...current,
                        smtp: { ...current.smtp, host: event.target.value },
                      }))
                    }
                  />
                </label>
                <label>
                  <span>{t("Port")}</span>
                  <input
                    type="number"
                    min={1}
                    max={65535}
                    required
                    value={form.smtp.port}
                    onChange={(event) =>
                      updateForm((current) => ({
                        ...current,
                        smtp: {
                          ...current.smtp,
                          port: Number(event.target.value),
                        },
                      }))
                    }
                  />
                </label>
                <label>
                  <span>{t("Transportverschlüsselung")}</span>
                  <select
                    value={form.smtp.security}
                    onChange={(event) =>
                      updateForm((current) => ({
                        ...current,
                        smtp: {
                          ...current.smtp,
                          security: event.target.value as
                            | "starttls"
                            | "tls"
                            | "plain",
                        },
                      }))
                    }
                  >
                    <option value="starttls">STARTTLS</option>
                    <option value="tls">{t("Implizites TLS")}</option>
                    <option value="plain">
                      {t("Unverschlüsselt · internes Relay")}
                    </option>
                  </select>
                </label>
                <label>
                  <span>{t("Benutzername")}</span>
                  <input
                    type="text"
                    autoComplete="username"
                    value={form.smtp.username}
                    onChange={(event) =>
                      updateForm((current) => ({
                        ...current,
                        smtp: {
                          ...current.smtp,
                          username: event.target.value,
                        },
                      }))
                    }
                  />
                </label>
                <label>
                  <span>{t("Passwort")}</span>
                  <input
                    type="password"
                    autoComplete="new-password"
                    required={
                      Boolean(form.smtp.username) &&
                      !settingsState?.smtp.password_configured
                    }
                    value={smtpPassword}
                    placeholder={
                      settingsState?.smtp.password_configured
                        ? t("Passwort hinterlegt · leer lassen zum Beibehalten")
                        : t("Optional bei Relay ohne Anmeldung")
                    }
                    onChange={(event) => {
                      setSmtpPassword(event.target.value);
                      setDirty(true);
                    }}
                  />
                </label>
              </div>
              {form.smtp.security === "plain" && (
                <div className="inline-warning">
                  <TriangleAlert aria-hidden="true" />
                  {t(
                    "Unverschlüsseltes SMTP nur in einem vertrauenswürdigen internen Netz verwenden.",
                  )}
                </div>
              )}
            </div>
          ) : (
            <div className="notification-transport-fields">
              <label className="notification-enable compact">
                <input
                  type="checkbox"
                  checked={form.graph.reuse_mailbox_connection}
                  onChange={(event) =>
                    updateForm((current) => ({
                      ...current,
                      graph: {
                        ...current.graph,
                        reuse_mailbox_connection: event.target.checked,
                      },
                    }))
                  }
                />
                <span>
                  <strong>
                    {t("Vorhandene Microsoft-365-Anbindung wiederverwenden")}
                  </strong>
                  <small>
                    {t(
                      "Tenant, Client-ID und Client Secret werden aus der gespeicherten Graph-Postfachanbindung übernommen.",
                    )}
                  </small>
                </span>
              </label>
              {!form.graph.reuse_mailbox_connection && (
                <div className="notification-fields graph-notification-fields">
                  <label>
                    <span>{t("Tenant-ID")}</span>
                    <input
                      type="text"
                      required
                      value={form.graph.tenant_id}
                      placeholder="00000000-0000-0000-0000-000000000000"
                      onChange={(event) =>
                        updateForm((current) => ({
                          ...current,
                          graph: {
                            ...current.graph,
                            tenant_id: event.target.value,
                          },
                        }))
                      }
                    />
                  </label>
                  <label>
                    <span>{t("Client-ID")}</span>
                    <input
                      type="text"
                      required
                      value={form.graph.client_id}
                      placeholder="00000000-0000-0000-0000-000000000000"
                      onChange={(event) =>
                        updateForm((current) => ({
                          ...current,
                          graph: {
                            ...current.graph,
                            client_id: event.target.value,
                          },
                        }))
                      }
                    />
                  </label>
                  <label>
                    <span>{t("Client Secret")}</span>
                    <input
                      type="password"
                      autoComplete="new-password"
                      required={!settingsState?.graph.client_secret_configured}
                      value={graphSecret}
                      placeholder={
                        settingsState?.graph.client_secret_configured
                          ? t("Secret hinterlegt · leer lassen zum Beibehalten")
                          : t("Secret-Wert, nicht die Secret-ID")
                      }
                      onChange={(event) => {
                        setGraphSecret(event.target.value);
                        setDirty(true);
                      }}
                    />
                  </label>
                </div>
              )}
              <div className="settings-note">
                <ShieldCheck aria-hidden="true" />
                <span>
                  {t(
                    "Die App-Registrierung benötigt Application Mail.Send. Der Zugriff sollte in Exchange Online auf das Absenderpostfach begrenzt werden.",
                  )}
                </span>
              </div>
            </div>
          )}

          <fieldset className="notification-cases">
            <legend>{t("Welche Fälle lösen eine E-Mail aus?")}</legend>
            <div>
              {NOTIFICATION_CASE_OPTIONS.map((option) => (
                <label key={option.value}>
                  <input
                    type="checkbox"
                    checked={form.cases.includes(option.value)}
                    onChange={() => toggleCase(option.value)}
                  />
                  <span>
                    <strong>{t(option.label)}</strong>
                    <small>{t(option.description)}</small>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          <div className="connection-actions">
            <button
              className="button button-primary"
              type="submit"
              disabled={busy !== null}
            >
              <Save aria-hidden="true" />
              {busy === "save"
                ? t("Wird gespeichert …")
                : t("Einstellungen speichern")}
            </button>
            <button
              className="button button-secondary"
              type="button"
              disabled={
                busy !== null || dirty || !settingsState?.configured
              }
              title={
                dirty
                  ? t("Speichere Änderungen vor dem Testversand.")
                  : undefined
              }
              onClick={sendTest}
            >
              <Send aria-hidden="true" />
              {busy === "test"
                ? t("Test-E-Mail wird versendet …")
                : t("Test-E-Mail senden")}
            </button>
          </div>

          <div className="notification-delivery-summary">
            <div>
              <span>{t("Frühere Gruppenversände: als erfolgreich gespeichert")}</span>
              <strong>{settingsState?.delivery.sent ?? 0}</strong>
            </div>
            <div>
              <span>{t("Frühere Gruppenversände: fehlgeschlagen oder ungeklärt")}</span>
              <strong>{(settingsState?.delivery.failed ?? 0) + (settingsState?.delivery.pending ?? 0)}</strong>
            </div>
            <div>
              <span>{t("Letzter Test")}</span>
              <strong>
                {settingsState?.tested_at
                  ? formatDate(settingsState.tested_at, true)
                  : t("Noch nicht durchgeführt")}
              </strong>
            </div>
          </div>

          <div className="settings-note">
            <Info aria-hidden="true" />
            <span>
              {t(
                "Jede E-Mail enthält HTML, Klartext, stabile X-DMARC-Control-Header und einen versionierten JSON-Anhang für Mailregeln oder SIEM-Workflows.",
              )}
            </span>
          </div>

          {settingsState && (settingsState.delivery.sent + settingsState.delivery.failed + settingsState.delivery.pending > 0) && (
            <p className="settings-note">
              {t("Frühere Gruppenversände bleiben erhalten. Da Ergebnisse je Empfänger fehlen, werden diese Warnungen nicht automatisch erneut versendet; auch frühere fehlgeschlagene oder ungeklärte Versuche bleiben angehalten.")}
            </p>
          )}
          {settingsState?.delivery.recipient_delivery && (
            <RecipientDeliveryStatus summary={settingsState.delivery.recipient_delivery} />
          )}

          {settingsState?.delivery.latest?.last_error && (
            <div className="inline-warning">
              <TriangleAlert aria-hidden="true" />
              {t("Letzter Versandfehler: {error}", {
                error: settingsState.delivery.latest.last_error,
              })}
            </div>
          )}

          {feedback && (
            <div className="settings-feedback" aria-live="polite">
              <StatusPill tone={feedbackTone}>{feedback}</StatusPill>
            </div>
          )}
        </form>
      )}
    </section>
  );
}

function BackupSettingsPanel({
  auth,
  setAuth,
}: {
  auth: AuthStatus;
  setAuth: (status: AuthStatus) => void;
}) {
  const { t, formatDate } = useI18n();
  const [settingsState, setSettingsState] = useState<BackupSettings | null>(null);
  const [mode, setMode] = useState<BackupMode | "">("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [feedbackTone, setFeedbackTone] = useState<
    "success" | "critical" | "info"
  >("info");

  const load = useCallback(() => {
    setLoading(true);
    api
      .backupSettings()
      .then((current) => {
        setSettingsState(current);
        setMode(current.mode === "unconfigured" ? "" : current.mode);
        setFeedback("");
      })
      .catch((reason: Error) => {
        setFeedbackTone("critical");
        setFeedback(reason.message || t("Backup-Status konnte nicht geladen werden."));
      })
      .finally(() => setLoading(false));
  }, [t]);

  useEffect(() => load(), [load]);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!mode) return;
    if (!auth.authenticated) {
      setFeedbackTone("critical");
      setFeedback(t("Melde dich zuerst als Admin an."));
      return;
    }
    const disablesIntegrated =
      settingsState?.mode === "integrated" && mode !== "integrated";
    if (
      (mode === "none" || disablesIntegrated) &&
      !window.confirm(
        t(
          "Integrierte Sicherungen wirklich deaktivieren? Vorhandene Backups bleiben erhalten.",
        ),
      )
    ) {
      return;
    }
    setSaving(true);
    setFeedback("");
    try {
      const updated = await api.updateBackupSettings(mode);
      setSettingsState(updated);
      setMode(updated.mode === "unconfigured" ? "" : updated.mode);
      setFeedbackTone("success");
      setFeedback(t("Backup-Strategie wurde gespeichert."));
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "";
      if (message === "Admin login required") {
        setAuth({ ...auth, authenticated: false });
      }
      setFeedbackTone("critical");
      setFeedback(
        message === "Admin login required"
          ? t("Die Admin-Sitzung ist abgelaufen. Bitte erneut anmelden.")
          : message || t("Backup-Strategie konnte nicht gespeichert werden."),
      );
    } finally {
      setSaving(false);
    }
  };

  const runtime = settingsState?.runtime;
  const runtimeTone =
    mode !== "integrated"
      ? ("neutral" as const)
      : runtime?.state === "success"
        ? ("success" as const)
        : runtime?.state === "error"
          ? ("critical" as const)
          : runtime?.state === "running" || runtime?.state === "restoring"
            ? ("info" as const)
            : ("neutral" as const);

  return (
    <section className="surface backup-settings">
      <div className="settings-title connection-title">
        <span className="settings-icon">
          <HardDriveDownload aria-hidden="true" />
        </span>
        <div>
          <h3>{t("Backup & Wiederherstellung")}</h3>
          <p>
            {t(
              "Lege fest, ob DMARC Control integrierte Dumps erstellt oder eine externe Sicherung verantwortlich ist.",
            )}
          </p>
        </div>
        <StatusPill tone={runtimeTone}>
          {mode !== "integrated"
            ? t("Integrierte Sicherung inaktiv")
            : runtime?.state === "success"
              ? t("Letztes Backup erfolgreich")
              : runtime?.state === "error"
                ? t("Backupfehler")
                : runtime?.state === "running"
                  ? t("Backup läuft")
                  : runtime?.state === "restoring"
                    ? t("Wiederherstellung läuft")
                    : t("Integrierte Sicherung aktiv")}
        </StatusPill>
      </div>

      {loading && !settingsState ? (
        <LoadingState label={t("Backup-Status wird geladen")} />
      ) : (
        <form className="backup-settings-form" onSubmit={save}>
          <BackupModeSelector value={mode} onChange={setMode} disabled={saving} />

          <div className="settings-note">
            <Info aria-hidden="true" />
            <span>
              {t(
                "Eine Containersicherung allein genügt nicht. Externe Sicherungen müssen die persistenten data-Verzeichnisse und die Konfiguration anwendungskonsistent erfassen.",
              )}
            </span>
          </div>

          {mode === "integrated" && settingsState?.recovery_key_ready && (
            <div className="backup-runtime-grid">
              <div>
                <span>{t("Letzter Erfolg")}</span>
                <strong>
                  {runtime?.last_success_at
                    ? formatDate(runtime.last_success_at, true)
                    : t("Noch kein erfolgreiches Backup")}
                </strong>
              </div>
              <div>
                <span>{t("Nächster Lauf")}</span>
                <strong>
                  {runtime?.next_run_at
                    ? formatDate(runtime.next_run_at, true)
                    : t("Wird geplant")}
                </strong>
              </div>
              <div>
                <span>{t("Recovery-Key-Fingerprint")}</span>
                <strong>{settingsState.recovery_key_fingerprint}</strong>
              </div>
            </div>
          )}

          {mode === "integrated" &&
            settingsState &&
            !settingsState.recovery_key_ready && (
              <div className="inline-warning">
                <TriangleAlert aria-hidden="true" />
                <span>
                  {t(
                    "Der Recovery-Key fehlt. Er wird nicht automatisch ersetzt, damit vorhandene Backups nicht unbemerkt unlesbar werden.",
                  )}
                </span>
              </div>
            )}

          {runtime?.message && (
            <div className={runtime.state === "error" ? "inline-warning" : "settings-note"}>
              {runtime.state === "error" ? (
                <TriangleAlert aria-hidden="true" />
              ) : (
                <Info aria-hidden="true" />
              )}
              <span>{runtime.message}</span>
            </div>
          )}

          {!auth.authenticated && (
            <div className="settings-note">
              <LockKeyhole aria-hidden="true" />
              <span>
                {t(
                  "Melde dich im Bereich Administration an, um die Backup-Strategie zu ändern.",
                )}
              </span>
            </div>
          )}

          <button
            className="button button-primary"
            type="submit"
            disabled={saving || !auth.authenticated || !mode || mode === settingsState?.mode}
          >
            <Save aria-hidden="true" />
            {saving ? t("Wird gespeichert …") : t("Backup-Strategie speichern")}
          </button>

          {feedback && (
            <div className="settings-feedback" aria-live="polite">
              <StatusPill tone={feedbackTone}>{feedback}</StatusPill>
            </div>
          )}
        </form>
      )}
    </section>
  );
}

function SettingsView({
  color,
  customColor,
  hasLocalBrand,
  appearance,
  appearanceError,
  auth,
  setAuth,
  updateColor,
  saveCustomColor,
  resetLocalBrand,
  updateGlobalAppearance,
  onDomainsChanged,
}: {
  color: string;
  customColor: string | null;
  hasLocalBrand: boolean;
  appearance: AppearanceSettings | null;
  appearanceError: string;
  auth: AuthStatus;
  setAuth: (status: AuthStatus) => void;
  onDomainsChanged: () => void;
  updateColor: (color: string) => void;
  saveCustomColor: () => void;
  resetLocalBrand: () => void;
  updateGlobalAppearance: (
    profile: AppearanceSettings["global_profile"],
    color: string | null,
  ) => Promise<AppearanceSettings>;
}) {
  const { language, setLanguage, t } = useI18n();
  const [message, setMessage] = useState("");
  const [messageTone, setMessageTone] = useState<
    "success" | "critical" | "info"
  >("info");
  const [savingGlobal, setSavingGlobal] = useState(false);
  const [settingsSection, setSettingsSection] =
    useState<SettingsSection>("appearance");
  const [mailboxSummary, setMailboxSummary] =
    useState<MailboxConnectionState | null>(null);
  const [loginPassword, setLoginPassword] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newPasswordConfirmation, setNewPasswordConfirmation] = useState("");
  const [readUsername, setReadUsername] = useState(auth.read_username ?? "");
  const [readPassword, setReadPassword] = useState("");
  const [readPasswordConfirmation, setReadPasswordConfirmation] = useState("");
  const [authMessage, setAuthMessage] = useState("");
  const [authMessageTone, setAuthMessageTone] = useState<
    "success" | "critical" | "info"
  >("info");
  const [authBusy, setAuthBusy] = useState(false);
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
    if (!auth.authenticated) {
      setMessageTone("critical");
      setMessage(t("Melde dich zuerst als Admin an."));
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
      await updateGlobalAppearance(profile, profileColor);
      setMessageTone("success");
      setMessage(t("Globaler Standard wurde aktualisiert."));
    } catch (reason) {
      const rawMessage =
        reason instanceof Error ? reason.message : t("Aktualisierung fehlgeschlagen.");
      if (rawMessage === "Admin login required") {
        setAuth({ ...auth, authenticated: false });
      }
      setMessageTone("critical");
      setMessage(
        rawMessage === "Admin login required"
          ? t("Die Admin-Sitzung ist abgelaufen. Bitte erneut anmelden.")
          : rawMessage,
      );
    } finally {
      setSavingGlobal(false);
    }
  };
  const login = async (event: FormEvent) => {
    event.preventDefault();
    setAuthBusy(true);
    setAuthMessage("");
    try {
      setAuth(await api.loginAdmin(loginPassword));
      setLoginPassword("");
      setAuthMessageTone("success");
      setAuthMessage(t("Als Admin angemeldet."));
    } catch (reason) {
      const rawMessage =
        reason instanceof Error ? reason.message : t("Anmeldung fehlgeschlagen.");
      setAuthMessageTone("critical");
      setAuthMessage(
        rawMessage === "Invalid admin password"
          ? t("Admin-Passwort ist falsch.")
          : rawMessage,
      );
    } finally {
      setAuthBusy(false);
    }
  };
  const logout = async () => {
    setAuthBusy(true);
    setAuthMessage("");
    try {
      setAuth(await api.logoutAdmin());
      setAuthMessageTone("info");
      setAuthMessage(t("Admin-Sitzung wurde beendet."));
    } catch (reason) {
      setAuthMessageTone("critical");
      setAuthMessage(
        reason instanceof Error ? reason.message : t("Abmeldung fehlgeschlagen."),
      );
    } finally {
      setAuthBusy(false);
    }
  };
  const changePassword = async (event: FormEvent) => {
    event.preventDefault();
    if (newPassword.length < 12) {
      setAuthMessageTone("critical");
      setAuthMessage(t("Das Admin-Passwort muss mindestens 12 Zeichen lang sein."));
      return;
    }
    if (newPassword !== newPasswordConfirmation) {
      setAuthMessageTone("critical");
      setAuthMessage(t("Die Passwörter stimmen nicht überein."));
      return;
    }
    setAuthBusy(true);
    setAuthMessage("");
    try {
      setAuth(await api.changeAdminPassword(currentPassword, newPassword));
      setCurrentPassword("");
      setNewPassword("");
      setNewPasswordConfirmation("");
      setAuthMessageTone("success");
      setAuthMessage(t("Admin-Passwort wurde geändert."));
    } catch (reason) {
      const rawMessage =
        reason instanceof Error ? reason.message : t("Passwortänderung fehlgeschlagen.");
      if (rawMessage === "Admin login required") {
        setAuth({ ...auth, authenticated: false });
      }
      setAuthMessageTone("critical");
      setAuthMessage(
        rawMessage === "Current admin password is invalid"
          ? t("Das aktuelle Admin-Passwort ist falsch.")
          : rawMessage === "New password must be different"
            ? t("Das neue Passwort muss sich vom aktuellen unterscheiden.")
            : rawMessage === "Admin login required"
              ? t("Die Admin-Sitzung ist abgelaufen. Bitte erneut anmelden.")
              : rawMessage,
      );
    } finally {
      setAuthBusy(false);
    }
  };
  const changeReadCredentials = async (event: FormEvent) => {
    event.preventDefault();
    if (!readUsername.trim() || /\s/.test(readUsername.trim())) {
      setAuthMessageTone("critical");
      setAuthMessage(t("Der Operator-Benutzername darf keine Leerzeichen enthalten."));
      return;
    }
    if (readPassword.length < 12) {
      setAuthMessageTone("critical");
      setAuthMessage(t("Das Operator-Passwort muss mindestens 12 Zeichen lang sein."));
      return;
    }
    if (readPassword !== readPasswordConfirmation) {
      setAuthMessageTone("critical");
      setAuthMessage(t("Die Operator-Passwörter stimmen nicht überein."));
      return;
    }
    setAuthBusy(true);
    setAuthMessage("");
    try {
      const next = await api.updateReadCredentials(
        readUsername.trim(),
        readPassword,
      );
      setAuth(next);
      setReadUsername(next.read_username ?? "");
      setReadPassword("");
      setReadPasswordConfirmation("");
      setAuthMessageTone("success");
      setAuthMessage(t("Operator-Zugang wurde aktualisiert."));
    } catch (reason) {
      const rawMessage =
        reason instanceof Error ? reason.message : t("Aktualisierung fehlgeschlagen.");
      if (rawMessage === "Admin login required") {
        setAuth({ ...auth, authenticated: false });
      }
      setAuthMessageTone("critical");
      setAuthMessage(
        rawMessage === "Admin login required"
          ? t("Die Admin-Sitzung ist abgelaufen. Bitte erneut anmelden.")
          : rawMessage,
      );
    } finally {
      setAuthBusy(false);
    }
  };
  const activeLabel = hasLocalBrand
    ? t("Lokale Farbgebung aktiv")
    : appearance?.global_profile === "custom"
      ? t("Globaler Standard: Custom")
      : t("Globaler Standard: Standardgrün");
  const mailboxNeedsAttention =
    auth.authenticated &&
    mailboxSummary !== null &&
    mailboxSummary.active_revision === null;
  const sectionStatus =
    settingsSection === "appearance"
      ? {
          tone: hasLocalBrand ? ("info" as const) : ("neutral" as const),
          label: activeLabel,
        }
      : settingsSection === "connection"
        ? {
            tone:
              mailboxSummary?.parser?.state === "error"
                ? ("critical" as const)
                : mailboxSummary?.active_revision
                  ? ("success" as const)
                  : ("neutral" as const),
            label: mailboxSummary?.active_revision
              ? t("GUI-verwaltet")
              : t("Bestehende Konfiguration"),
          }
        : settingsSection === "backup"
          ? {
              tone: "neutral" as const,
              label: t("Backup-Strategie"),
            }
        : {
            tone: auth.authenticated
              ? ("success" as const)
              : ("neutral" as const),
            label: auth.authenticated
              ? t("Admin angemeldet")
              : t("Nicht angemeldet"),
          };

  return (
    <div className="page-stack settings-page">
      <SectionHeader
        title={t("Einstellungen")}
        subtitle={t(
          "Darstellung, Domains, Benachrichtigungen, Postfachanbindung, Backup und geschützte Administration",
        )}
        action={
          <StatusPill tone={sectionStatus.tone}>
            {sectionStatus.label}
          </StatusPill>
        }
      />

      <div className="settings-grid">
        <nav
          className="settings-subnav surface"
          aria-label={t("Einstellungsbereiche")}
        >
          <button
            type="button"
            className={classNames(
              settingsSection === "appearance" && "active",
            )}
            aria-current={
              settingsSection === "appearance" ? "page" : undefined
            }
            onClick={() => setSettingsSection("appearance")}
          >
            <Palette aria-hidden="true" />
            <span>
              <strong>{t("Darstellung & Sprache")}</strong>
              <small>{t("Branding und Benutzeroberfläche")}</small>
            </span>
            <ChevronRight aria-hidden="true" />
          </button>
          <button
            type="button"
            className={classNames(
              settingsSection === "notifications" && "active",
            )}
            aria-current={
              settingsSection === "notifications" ? "page" : undefined
            }
            onClick={() => setSettingsSection("notifications")}
          >
            <Bell aria-hidden="true" />
            <span>
              <strong>{t("Benachrichtigungen")}</strong>
              <small>{t("E-Mail-Alerting und Versandwege")}</small>
            </span>
            <ChevronRight aria-hidden="true" />
          </button>
          <button type="button" className={classNames(settingsSection === "domains" && "active")}
            aria-current={settingsSection === "domains" ? "page" : undefined}
            onClick={() => setSettingsSection("domains")}>
            <Globe2 aria-hidden="true" />
            <span><strong>{t("Domains")}</strong><small>{t("Report-Eingang und Wartefristen")}</small></span>
            <ChevronRight aria-hidden="true" />
          </button>
          <button
            type="button"
            className={classNames(
              settingsSection === "connection" && "active",
            )}
            aria-current={
              settingsSection === "connection" ? "page" : undefined
            }
            onClick={() => setSettingsSection("connection")}
          >
            <PlugZap aria-hidden="true" />
            <span>
              <strong>{t("Postfachanbindung")}</strong>
              <small>{t("Microsoft 365 oder IMAP")}</small>
            </span>
            {mailboxNeedsAttention ? (
              <span
                className="settings-nav-indicator"
                title={t("Einrichtung ausstehend")}
                aria-label={t("Einrichtung ausstehend")}
              />
            ) : (
              <ChevronRight aria-hidden="true" />
            )}
          </button>
          <button
            type="button"
            className={classNames(settingsSection === "backup" && "active")}
            aria-current={settingsSection === "backup" ? "page" : undefined}
            onClick={() => setSettingsSection("backup")}
          >
            <HardDriveDownload aria-hidden="true" />
            <span>
              <strong>{t("Backup & Wiederherstellung")}</strong>
              <small>{t("Dumps oder externe Sicherung")}</small>
            </span>
            <ChevronRight aria-hidden="true" />
          </button>
          <button
            type="button"
            className={classNames(
              settingsSection === "administration" && "active",
            )}
            aria-current={
              settingsSection === "administration" ? "page" : undefined
            }
            onClick={() => setSettingsSection("administration")}
          >
            <LockKeyhole aria-hidden="true" />
            <span>
              <strong>{t("Administration")}</strong>
              <small>{t("Operator-Zugang und Admin-Passwort")}</small>
            </span>
            <ChevronRight aria-hidden="true" />
          </button>
        </nav>

        {mailboxNeedsAttention && settingsSection !== "connection" && (
          <button
            className="settings-setup-hint"
            type="button"
            onClick={() => setSettingsSection("connection")}
          >
            <PlugZap aria-hidden="true" />
            <span>
              <strong>
                {mailboxSummary?.configured
                  ? t("Postfachanbindung wartet auf Aktivierung")
                  : t("Postfachanbindung im GUI einrichten")}
              </strong>
              <small>
                {mailboxSummary?.configured
                  ? t(
                      "Der gespeicherte Entwurf ist noch nicht als aktive Verbindung übernommen.",
                    )
                  : t(
                      "Die bestehende Parser-Konfiguration läuft weiter, bis eine geprüfte GUI-Verbindung aktiviert wird.",
                    )}
              </small>
            </span>
            <span className="settings-hint-action">
              {mailboxSummary?.configured
                ? t("Anbindung prüfen")
                : t("Jetzt einrichten")}
              <ChevronRight aria-hidden="true" />
            </span>
          </button>
        )}

        <div
          className="settings-notification-slot"
          hidden={settingsSection !== "notifications"}
        >
          <NotificationSettingsPanel auth={auth} setAuth={setAuth} />
        </div>

        <div className="settings-domains-slot" hidden={settingsSection !== "domains"}>
          <DomainMonitoringSettings active={settingsSection === "domains"} auth={auth} setAuth={setAuth}
            onChanged={onDomainsChanged} onAdminLogin={() => setSettingsSection("administration")} />
        </div>

        <div
          className="settings-connection-slot"
          hidden={settingsSection !== "connection"}
        >
          <MailboxConnectionSettings
            auth={auth}
            setAuth={setAuth}
            onStateChange={setMailboxSummary}
          />
        </div>

        <div
          className="settings-backup-slot"
          hidden={settingsSection !== "backup"}
        >
          <BackupSettingsPanel auth={auth} setAuth={setAuth} />
        </div>

        <section
          className="surface language-settings"
          hidden={settingsSection !== "appearance"}
        >
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

        <section
          className="surface admin-settings"
          hidden={settingsSection !== "administration"}
        >
          <div className="settings-title">
            <span className="settings-icon">
              <LockKeyhole aria-hidden="true" />
            </span>
            <div>
              <h3>{t("Administration")}</h3>
              <p>
                {t(
                  "Der Operator-Zugang schützt das Dashboard und erlaubt die vorgesehene Alarm- und Host-Triage. Die separate Admin-Anmeldung schützt globale Einstellungen.",
                )}
              </p>
            </div>
            <StatusPill tone={auth.authenticated ? "success" : "neutral"}>
              {auth.authenticated
                ? t("Admin angemeldet")
                : t("Nicht angemeldet")}
            </StatusPill>
          </div>

          {!auth.authenticated ? (
            <form className="admin-login-form" onSubmit={login}>
              <label>
                <span>{t("Admin-Passwort")}</span>
                <input
                  type="password"
                  autoComplete="current-password"
                  maxLength={256}
                  required
                  value={loginPassword}
                  onChange={(event) => setLoginPassword(event.target.value)}
                />
              </label>
              <button
                className="button button-primary"
                type="submit"
                disabled={authBusy}
              >
                {t("Als Admin anmelden")}
              </button>
            </form>
          ) : (
            <>
              <form className="password-change-form" onSubmit={changePassword}>
                <label>
                  <span>{t("Aktuelles Passwort")}</span>
                  <input
                    type="password"
                    autoComplete="current-password"
                    required
                    value={currentPassword}
                    onChange={(event) => setCurrentPassword(event.target.value)}
                  />
                </label>
                <label>
                  <span>{t("Neues Passwort")}</span>
                  <input
                    type="password"
                    autoComplete="new-password"
                    minLength={12}
                    maxLength={256}
                    required
                    value={newPassword}
                    onChange={(event) => setNewPassword(event.target.value)}
                  />
                </label>
                <label>
                  <span>{t("Neues Passwort wiederholen")}</span>
                  <input
                    type="password"
                    autoComplete="new-password"
                    minLength={12}
                    maxLength={256}
                    required
                    value={newPasswordConfirmation}
                    onChange={(event) =>
                      setNewPasswordConfirmation(event.target.value)
                    }
                  />
                </label>
                <div className="admin-actions">
                  <button
                    className="button button-secondary"
                    type="submit"
                    disabled={authBusy}
                  >
                    {t("Passwort ändern")}
                  </button>
                  <button
                    className="button button-ghost"
                    type="button"
                    disabled={authBusy}
                    onClick={logout}
                  >
                    {t("Abmelden")}
                  </button>
                </div>
              </form>
              <small>
                {t(
                  "Nach einer Passwortänderung werden andere Admin-Sitzungen automatisch beendet.",
                )}
              </small>
              <div className="credential-section">
                <div>
                  <strong>{t("Operator-Zugang")}</strong>
                  <small>
                    {t(
                      "Eine Änderung beendet alle anderen Operator-Sitzungen. Diese Sitzung bleibt angemeldet.",
                    )}
                  </small>
                </div>
                <form
                  className="password-change-form"
                  onSubmit={changeReadCredentials}
                >
                  <label>
                    <span>{t("Operator-Benutzername")}</span>
                    <input
                      type="text"
                      autoComplete="username"
                      maxLength={120}
                      required
                      value={readUsername}
                      onChange={(event) => setReadUsername(event.target.value)}
                    />
                  </label>
                  <label>
                    <span>{t("Neues Operator-Passwort")}</span>
                    <input
                      type="password"
                      autoComplete="new-password"
                      minLength={12}
                      maxLength={256}
                      required
                      value={readPassword}
                      onChange={(event) => setReadPassword(event.target.value)}
                    />
                  </label>
                  <label>
                    <span>{t("Operator-Passwort wiederholen")}</span>
                    <input
                      type="password"
                      autoComplete="new-password"
                      minLength={12}
                      maxLength={256}
                      required
                      value={readPasswordConfirmation}
                      onChange={(event) =>
                        setReadPasswordConfirmation(event.target.value)
                      }
                    />
                  </label>
                  <div className="admin-actions">
                    <button
                      className="button button-secondary"
                      type="submit"
                      disabled={authBusy}
                    >
                      {t("Operator-Zugang aktualisieren")}
                    </button>
                  </div>
                </form>
              </div>
            </>
          )}
          {authMessage && (
            <div className="settings-feedback" aria-live="polite">
              <StatusPill tone={authMessageTone}>{authMessage}</StatusPill>
            </div>
          )}
        </section>

        <section
          className="surface brand-settings"
          hidden={settingsSection !== "appearance"}
        >
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

        <section
          className="surface brand-preview-section"
          hidden={settingsSection !== "appearance"}
        >
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

        <section
          className="surface profile-settings"
          hidden={settingsSection !== "appearance"}
        >
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
                  disabled={
                    !customColor || savingGlobal || !auth.authenticated
                  }
                  onClick={() => setGlobal("custom", customColor)}
                  title={
                    auth.authenticated
                      ? undefined
                      : t("Admin-Anmeldung erforderlich")
                  }
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
                  disabled={savingGlobal || !auth.authenticated}
                  onClick={() => setGlobal("standard", null)}
                  title={
                    auth.authenticated
                      ? undefined
                      : t("Admin-Anmeldung erforderlich")
                  }
                >
                  {t("Global setzen")}
                </button>
              </div>
            </article>
          </div>

          {!auth.authenticated && (
            <div className="settings-note">
              <LockKeyhole aria-hidden="true" />
              <span>
                {t(
                  "Melde dich im Bereich Administration an, um ein Profil global zu setzen.",
                )}
              </span>
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
  openHosts: (ip: string, domain?: string) => void;
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

  const [reloadKey, setReloadKey] = useState(0);
  const load = useCallback(() => setReloadKey((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setData(null);
    api.overview(domain, days, controller.signal)
      .then((next) => { if (!controller.signal.aborted) setData(next); })
      .catch((reason: Error) => { if (!controller.signal.aborted) setError(reason.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [domain, days, refreshKey, reloadKey]);

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
                        <button className="cell-link" type="button" aria-label={t("Quelle {ip} untersuchen", { ip: source.source_ip })} onClick={() => openHosts(source.source_ip, source.header_from ?? undefined)}>
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
  targetHostIp,
  originAlertId,
  clearTargetHost,
  selectHost,
  returnToAlert,
}: {
  domain: string;
  days: number;
  refreshKey: number;
  targetHostIp?: string;
  originAlertId?: string;
  clearTargetHost: () => void;
  selectHost: (ip: string) => void;
  returnToAlert: () => void;
}) {
  const { t, formatNumber, formatDate, translateBackendLabel } = useI18n();
  const [hosts, setHosts] = useState<Host[]>([]);
  const [risk, setRisk] = useState("all");
  const [search, setSearch] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [pagination, setPagination] = useState({ scope: "", offset: 0 });
  const [total, setTotal] = useState(0);
  const [reloadKey, setReloadKey] = useState(0);
  const { request } = useUnsavedChanges();
  const focusedContext = useRef("");
  const [selected, setSelected] = useState<Host | null>(null);
  const selectedContext = useRef("");
  const loadedDetailContext = useRef("");
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const pageSize = 100;
  const hostList = useRef<HTMLElement>(null);
  const loadedList = useRef("");
  const pageFocus = useRef<{ view: string; list: string; initiator: Element | null } | null>(null);
  const scope = JSON.stringify([domain, days, risk, searchQuery]);
  const offset = pagination.scope === scope ? pagination.offset : 0;
  const activeIp = targetHostIp;
  const searchPending = search.trim() !== searchQuery;
  const pageFocusView = JSON.stringify([scope, search, refreshKey, reloadKey, activeIp]);
  const listContext = JSON.stringify([scope, offset, refreshKey, reloadKey]);
  const changePage = (nextOffset: number) => {
    pageFocus.current = { view: pageFocusView,
      list: JSON.stringify([scope, nextOffset, refreshKey, reloadKey]), initiator: document.activeElement };
    setPagination({ scope, offset: nextOffset });
  };

  useLayoutEffect(() => {
    const intent = pageFocus.current;
    if (!intent) return;
    if (intent.view !== pageFocusView || (!loading && error)) {
      pageFocus.current = null;
      return;
    }
    if (loading || searchPending || intent.list !== listContext || loadedList.current !== intent.list) return;
    pageFocus.current = null;
    // A user who started editing or investigating during the request keeps focus.
    if (document.activeElement !== document.body && document.activeElement !== intent.initiator) return;
    hostList.current?.focus({ preventScroll: true });
    hostList.current?.scrollIntoView({ block: "start" });
  }, [pageFocusView, listContext, loading, searchPending, error, hosts]);

  const load = useCallback(() => setReloadKey((value) => value + 1), []);

  useEffect(() => {
    const timeout = window.setTimeout(() => setSearchQuery(search.trim()), 250);
    return () => window.clearTimeout(timeout);
  }, [search]);

  useEffect(() => {
    setPagination((current) => current.scope === scope ? current : { scope, offset: 0 });
  }, [scope]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setHosts([]);
    setTotal(0);
    api.hosts(domain, days, risk, {
      limit: pageSize,
      offset,
      search: searchQuery,
      signal: controller.signal,
    })
      .then((page) => {
        if (controller.signal.aborted) return;
        if (offset > 0 && offset >= page.total) {
          const nextOffset = Math.max(0, Math.floor((page.total - 1) / pageSize) * pageSize);
          if (pageFocus.current?.list === JSON.stringify([scope, offset, refreshKey, reloadKey])) {
            pageFocus.current.list = JSON.stringify([scope, nextOffset, refreshKey, reloadKey]);
          }
          setPagination({
            scope,
            offset: nextOffset,
          });
          return;
        }
        loadedList.current = JSON.stringify([scope, offset, refreshKey, reloadKey]);
        setHosts(page.items);
        setTotal(page.total);
      })
      .catch((reason: Error) => {
        if (!controller.signal.aborted) setError(reason.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [domain, days, risk, searchQuery, offset, scope, refreshKey, reloadKey]);

  useEffect(() => {
    const controller = new AbortController();
    const context = JSON.stringify([activeIp, domain, days]);
    if (selectedContext.current !== context) setSelected(null);
    selectedContext.current = context;
    setDetailError("");
    setDetailLoading(Boolean(activeIp));
    if (activeIp) {
      api.host(activeIp, domain, days, controller.signal)
        .then((host) => {
          if (!controller.signal.aborted) {
            loadedDetailContext.current = context;
            setSelected(host);
          }
        })
        .catch((reason: Error) => {
          if (controller.signal.aborted) return;
          if (reason instanceof ApiError && reason.status === 404) request(() => {
            if (!controller.signal.aborted) setSelected(null);
          });
          setDetailError(
            reason instanceof ApiError && reason.status === 404
              ? t("Die Quelle {ip} ist für die gewählte Domain und den Zeitraum nicht vorhanden. Passe die Filter an.", { ip: activeIp })
              : reason.message,
          );
        })
        .finally(() => {
          if (!controller.signal.aborted) setDetailLoading(false);
        });
    }
    return () => controller.abort();
  }, [activeIp, domain, days, refreshKey, reloadKey, t]);

  useEffect(() => {
    const context = JSON.stringify([activeIp, domain, days]);
    if (!activeIp) { focusedContext.current = ""; return; }
    if (!selected || selected.source_ip !== activeIp || loadedDetailContext.current !== context || focusedContext.current === activeIp) return;
    const heading = document.getElementById("host-detail-heading");
    if (heading) {
      focusedContext.current = activeIp;
      heading.focus({ preventScroll: true });
      heading.scrollIntoView({ block: "start" });
    }
  }, [selected, activeIp, domain, days]);

  const closeDetail = () => request(() => {
    const sourceIp = activeIp;
    setSelected(null);
    clearTargetHost();
    window.requestAnimationFrame(() => document.getElementById(`host-open-${sourceIp}`)?.focus());
  });
  const listLoading = loading || searchPending;

  return (
    <div className="page-stack hosts-page">
      <SectionHeader
        title="Sending Hosts"
        subtitle={t(
          "Technische Quellen, erkannte Dienste und Authentifizierungsergebnis",
        )}
        action={
          <StatusPill tone="neutral">
            {listLoading
              ? t("Sending Hosts werden geladen")
              : t("{count} Quellen", { count: formatNumber(total) })}
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

      <section className="surface host-list" ref={hostList} tabIndex={-1} aria-label="Sending Hosts" aria-busy={listLoading}>
        {listLoading ? (
          <LoadingState label={t("Sending Hosts werden geladen")} />
        ) : error ? null : hosts.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("Source")}</th>
                  <th>{t("Erkannter Dienst")}</th>
                  <th>{t("Zuordnung")}</th>
                  <th
                    title={t(
                      "Die Zahlen zeigen betroffene Nachrichten im gewählten Zeitraum.",
                    )}
                  >
                    Alignment
                  </th>
                  <th>DMARC</th>
                  <th className="numeric">{t("Nachrichten")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {hosts.map((host) => (
                  <tr
                    className={activeIp === host.source_ip ? "selected-row" : ""}
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
                        {classificationMode(host) === "automatic"
                          ? translateBackendLabel(host.service_detection.service)
                          : host.service_detection.service}
                      </strong>
                      <small>
                        {classificationMode(host) === "automatic" ? <>
                          {t("Konfidenz")} {translateBackendLabel(host.service_detection.confidence_label)}
                          {host.service_detection.confidence != null && ` · ${Math.round(host.service_detection.confidence * 100)} %`}
                        </> : t(classificationMode(host) === "manual" ? "Manuell" : "Übernommen")}
                      </small>
                      {host.service_detection.profile === "dynamic_ip" && (
                        <small className="dynamic-source-label">
                          <TriangleAlert aria-hidden="true" />
                          {t("Netzprofil · Dynamische IP")}
                        </small>
                      )}
                    </td>
                    <td>
                      <ClassificationPill status={host.trust_status} />
                    </td>
                    <td>
                      <span>
                        SPF ·{" "}
                        {host.spf_not_aligned
                          ? t("{count} von {total} nicht aligned", {
                              count: formatNumber(host.spf_not_aligned),
                              total: formatNumber(
                                host.spf_aligned + host.spf_not_aligned,
                              ),
                            })
                          : t("{count} von {total} aligned", {
                              count: formatNumber(host.spf_aligned),
                              total: formatNumber(
                                host.spf_aligned + host.spf_not_aligned,
                              ),
                            })}
                      </span>
                      <small>
                        DKIM ·{" "}
                        {host.dkim_not_aligned
                          ? t("{count} von {total} nicht aligned", {
                              count: formatNumber(host.dkim_not_aligned),
                              total: formatNumber(
                                host.dkim_aligned + host.dkim_not_aligned,
                              ),
                            })
                          : t("{count} von {total} aligned", {
                              count: formatNumber(host.dkim_aligned),
                              total: formatNumber(
                                host.dkim_aligned + host.dkim_not_aligned,
                              ),
                            })}
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
                        id={`host-open-${host.source_ip}`}
                        aria-label={t("Details für Quelle {ip}", { ip: host.source_ip })}
                        onClick={() => {
                          if (activeIp === host.source_ip) document.getElementById("host-detail-heading")?.focus();
                          else selectHost(host.source_ip);
                        }}
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

      {!listLoading && !error && total > 0 && (
        <nav className="list-pagination" aria-label={t("Sending-Hosts-Seiten")}>
          <span aria-live="polite">
            {t("{start}–{end} von {total} Quellen", {
              start: formatNumber(offset + 1),
              end: formatNumber(offset + hosts.length),
              total: formatNumber(total),
            })}
          </span>
          <div className="row-actions">
            <button
              className="button button-secondary"
              type="button"
              disabled={offset === 0}
              onClick={() => changePage(Math.max(0, offset - pageSize))}
            >
              {t("Vorherige Seite")}
            </button>
            <button
              className="button button-secondary"
              type="button"
              disabled={offset + hosts.length >= total}
              onClick={() => changePage(offset + pageSize)}
            >
              {t("Nächste Seite")}
            </button>
          </div>
        </nav>
      )}

      {detailLoading && <LoadingState label={t("Host-Detail wird geladen")} />}
      {detailError && (
        <section className="surface">
          <ErrorState message={detailError} retry={load} />
          <div className="row-actions">
            {originAlertId && (
              <button className="button button-secondary" type="button" onClick={returnToAlert}>
                {t("Zurück zur Warnung")}
              </button>
            )}
            <button className="button button-ghost" type="button" onClick={closeDetail}>
              {t("Detailansicht schließen")}
            </button>
          </div>
        </section>
      )}
      {selected && (
        <HostDetail
          key={selected.source_ip}
          host={selected}
          close={closeDetail}
          saved={load}
          originAlertId={originAlertId}
          returnToAlert={returnToAlert}
        />
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

function ClassificationPill({ status }: { status: TrustStatus }) {
  const { t } = useI18n();
  const values: Record<TrustStatus, { label: string; tone: "neutral" | "info" | "success" }> = {
    unconfirmed: { label: t("Prüfung ausstehend"), tone: "neutral" },
    automatic: { label: t("Automatisch zugeordnet"), tone: "info" },
    confirmed: {
      label: t("Zuordnung bestätigt"),
      tone: "success",
    },
    ignored: {
      label: t("Automatische Zuordnung verworfen"),
      tone: "neutral",
    },
  };
  const value = values[status];
  return <StatusPill tone={value.tone}>{value.label}</StatusPill>;
}

function HostDetail({
  host,
  close,
  saved,
  originAlertId,
  returnToAlert,
}: {
  host: Host;
  close: () => void;
  saved: () => void;
  originAlertId?: string;
  returnToAlert: () => void;
}) {
  const { t, formatNumber, formatDate, translateBackendLabel } = useI18n();
  const isDynamicIp = host.service_detection.profile === "dynamic_ip";

  return (
    <section className="surface host-detail" aria-live="polite">
      {originAlertId && (
        <div className="investigation-context">
          <div>
            <Bell aria-hidden="true" />
            <span>
              {t(
                "Untersuchung aus der Warnungszentrale. Alert-Status und Host-Zuordnung werden getrennt gespeichert.",
              )}
            </span>
          </div>
          <button
            className="button button-secondary"
            type="button"
            onClick={returnToAlert}
          >
            <ArrowLeft aria-hidden="true" />
            {t("Zurück zur Warnung")}
          </button>
        </div>
      )}
      <div className="host-detail-head">
        <div>
          <div className="eyebrow">{t("Host-Detail")}</div>
          <h2 id="host-detail-heading" tabIndex={-1}>
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

      {isDynamicIp && (
        <div className="dynamic-source-notice">
          <TriangleAlert aria-hidden="true" />
          <div>
            <strong>{t("Dynamischer öffentlicher IP-Bereich")}</strong>
            <p>
              {host.dmarc_fail
                ? t(
                    "Das Muster entspricht einem Endkunden- oder Zugangsnetz. Zusammen mit dem DMARC-Fail ist dies ein starkes Indiz für Spoofing oder Spam; eine Fehlkonfiguration bleibt möglich.",
                  )
                : t(
                    "Das Muster entspricht einem Endkunden- oder Zugangsnetz. Solche Adressen sind für direkte Mailzustellung ungewöhnlich und sollten geprüft werden.",
                  )}
            </p>
          </div>
        </div>
      )}

      <HostServiceDetection host={host} />
      <HostClassificationForm host={host} saved={saved} />
      <div className="settings-note classification-note">
        <Info aria-hidden="true" />
        <span>
          {t(
            "Der Zuordnungsstatus beschreibt nur die Dienstklassifizierung. Er ändert weder das DMARC-Ergebnis noch Warnungen und ist keine Freigabeliste.",
          )}
        </span>
      </div>
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
  adminAuthenticated,
  domain,
  days,
  refreshKey,
  targetAlertId,
  investigateHost,
}: {
  adminAuthenticated: boolean;
  domain: string;
  days: number;
  refreshKey: number;
  targetAlertId?: string;
  investigateHost: (alert: Alert) => void;
}) {
  const { language, t, formatNumber, formatDate, reportAge } = useI18n();
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [deliveryAlert, setDeliveryAlert] = useState<Alert | null>(null);
  useEffect(() => setDeliveryAlert(null), [domain, days, adminAuthenticated]);
  const [status, setStatus] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [statusCounts, setStatusCounts] = useState<import("./api").AlertStatusCounts | null>(null);
  const focusedOnce = useRef<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [targetResult, setTargetResult] = useState<{
    requestedId: string;
    alert: Alert;
  } | null>(null);
  const [targetLoading, setTargetLoading] = useState(false);
  const [targetError, setTargetError] = useState("");
  const [targetReloadKey, setTargetReloadKey] = useState(0);
  const targetAlert = targetResult && targetResult.requestedId === targetAlertId
    ? targetResult.alert
    : null;
  const focusedTargetId = targetAlert?.id ?? targetAlertId;
  const outsideAlert = targetAlert && !alerts.some((item) => item.id === targetAlert.id)
    ? targetAlert
    : null;

  const load = useCallback(() => setReloadKey((value) => value + 1), []);
  const { update, pending, error: updateError, clearError: clearUpdateError } = useAlertUpdates(
    JSON.stringify([domain, days, status]),
    () => { load(); setTargetReloadKey((value) => value + 1); },
  );

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setAlerts([]);
    setStatusCounts(null);
    api.alerts(domain, days, status, controller.signal)
      .then((page) => {
        if (!controller.signal.aborted) { setAlerts(page.items); setStatusCounts(page.status_counts ?? null); }
      })
      .catch((reason: Error) => {
        if (!controller.signal.aborted) setError(reason.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [domain, days, status, refreshKey, reloadKey]);

  useEffect(() => {
    const controller = new AbortController();
    setTargetError("");
    setTargetResult(null);
    if (!targetAlertId || alerts.some((item) => item.id === targetAlertId)) {
      setTargetLoading(false);
      return () => controller.abort();
    }
    if (loading) return () => controller.abort();
    setTargetLoading(true);
    api.alert(targetAlertId, controller.signal)
      .then((alert) => {
        if (!controller.signal.aborted) setTargetResult({ requestedId: targetAlertId, alert });
      })
      .catch((reason: Error) => {
        if (controller.signal.aborted) return;
        setTargetError(
          reason instanceof ApiError && reason.status === 404
            ? t("Die verlinkte Warnung wurde nicht gefunden. Für ältere Links ist möglicherweise kein gespeichertes Ereignis vorhanden.")
            : reason.message,
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) setTargetLoading(false);
      });
    return () => controller.abort();
  }, [alerts, loading, targetAlertId, targetReloadKey, t]);

  useEffect(() => {
    if (!focusedTargetId) { focusedOnce.current = null; return; }
    if (loading || focusedOnce.current === focusedTargetId) return;
    const target = document.getElementById(`alert-${focusedTargetId}`);
    if (target) {
      focusedOnce.current = focusedTargetId;
      target.focus({ preventScroll: true });
      target.scrollIntoView({ block: "center" });
    }
  }, [alerts, loading, focusedTargetId, outsideAlert]);

  const openCount = !loading && !error ? statusCounts?.open : undefined;
  const alertTitle = (alert: Alert) => t(alert.title);
  const alertTrigger = (alert: Alert) => {
    if (alert.kind === "stale-reports") {
      if (alert.freshness_reason === "never_observed") {
        return t("Seit dem Überwachungsbeginn am {date} ist kein erster Report eingegangen; die Wartefrist von {days} Tagen ist abgelaufen.", {
          date: formatDate(alert.monitoring_started_at, true), days: alert.grace_days ?? "–",
        });
      }
      if (alert.freshness_reason === "reactivated") {
        return t("Seit der Reaktivierung am {date} liegt kein aktueller Report vor; die neue Wartefrist von {days} Tagen ist abgelaufen.", {
          date: formatDate(alert.monitoring_started_at, true), days: alert.grace_days ?? "–",
        });
      }
    }
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
      if (!alert.report_time || !Number.isFinite(new Date(alert.report_time).getTime())) {
        return t("Es fehlen aktuelle DMARC-Reports; die Wartefrist ist abgelaufen.");
      }
      const days = Math.max(
        0,
        Math.floor(
          (Date.now() - new Date(alert.report_time ?? "").getTime()) /
            86_400_000,
        ),
      );
      return t(
        "Letzter Berichtszeitraum endete vor {days} Tagen; übliche Zustellverzögerung berücksichtigt",
        { days },
      );
    }
    return alert.trigger;
  };
  const renderAlertTable = (items: Alert[]) => (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>{t("Priorität")}</th>
            <th>{t("Warnung")}</th>
            <th>{t("Auslöser")}</th>
            <th>{t("Reportzeit")}</th>
            <th>{t("Status")}</th>
            <th>{t("Versand")}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {items.map((alert) => (
            <tr
              key={alert.id}
              id={`alert-${alert.id}`}
              tabIndex={-1}
              className={classNames(
                focusedTargetId === alert.id && "selected-row",
              )}
            >
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
                {isExpectedProviderPassAlert(alert) && (
                  <span
                    className="alert-provider-context"
                    title={t("Die Zuordnung gilt für diesen DMARC-bestandenen Host. DMARC-Fehler bleiben kritisch.")}
                  >
                    <CheckCircle2 aria-hidden="true" />
                    {alert.provider_group_label
                      ? t("{service} · erwarteter Versanddienst · DMARC bestanden", {
                          service: alert.provider_group_label,
                        })
                      : t("Erwarteter Versanddienst · DMARC bestanden")}
                  </span>
                )}
              </td>
              <td>
                <span>{alertTrigger(alert)}</span>
                <small className="alert-message-count">
                  {alert.source_ip && alert.total_messages !== undefined
                    ? t("{affected} von {total} Nachrichten betroffen", {
                        affected: formatNumber(alert.messages),
                        total: formatNumber(alert.total_messages),
                      })
                    : `${formatNumber(alert.messages)} ${t("Nachrichten")}`}
                </small>
              </td>
              <td>
                <span>{formatDate(alert.report_time)}</span>
                <small>{reportAge(alert.report_time)}</small>
              </td>
              <td><AlertStatusPill status={alert.status} /></td>
              <td>
                {alert.delivery && <AlertDeliveryBadge summary={alert.delivery} />}
                {adminAuthenticated && (
                  <button id={`delivery-${alert.id}`} className="cell-link" type="button"
                    onClick={() => setDeliveryAlert(alert)}>{t("Versanddetails")}</button>
                )}
              </td>
              <td className="numeric">
                <div className="row-actions">
                  {alert.status === "open" && (
                    <button
                      className="button button-secondary"
                      type="button"
                      disabled={pending.has(alert.id)}
                      onClick={() => update(alert.id, "acknowledged")}
                    >
                      {t("Bestätigen")}
                    </button>
                  )}
                  {alert.source_ip && (
                    <button
                      className="button button-secondary"
                      type="button"
                      disabled={pending.has(alert.id)}
                      aria-label={t("Quelle {ip} untersuchen", { ip: alert.source_ip })}
                      onClick={() => investigateHost(alert)}
                    >
                      <Server aria-hidden="true" />
                      {t("Sending Host untersuchen")}
                    </button>
                  )}
                  {alert.status !== "open" && (
                    <button className="button button-secondary" type="button"
                      disabled={pending.has(alert.id)} onClick={() => update(alert.id, "open")}>
                      {t("Wieder öffnen")}
                    </button>
                  )}
                  {alert.status !== "resolved" && (
                    <button
                      className="button button-ghost"
                      type="button"
                      disabled={pending.has(alert.id)}
                      onClick={() => update(alert.id, "resolved")}
                    >
                      {t("Behoben")}
                    </button>
                  )}
                  {alert.status !== "ignored" && (
                    <button
                      className="button button-ghost"
                      type="button"
                      disabled={pending.has(alert.id)}
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
  );
  return (
    <div className="page-stack alerts-page">
      <SectionHeader
        title={t("Warnungszentrale")}
        subtitle={t(
          "Deduplizierte Ereignisse mit nachvollziehbarem Auslöser",
        )}
        action={
          <span title={t("Offene Warnungen für die gewählte Domain und den Zeitraum, unabhängig vom Statusfilter.")}>
            <StatusPill tone={openCount === undefined ? "neutral" : openCount ? "critical" : "success"}>
              {openCount === undefined ? t(loading ? "Offenzahl wird geladen" : "Offenzahl nicht verfügbar") : t("{count} offen", { count: formatNumber(openCount) })}
            </StatusPill>
          </span>
        }
      />
      <AlertEvaluationMonitor refreshKey={refreshKey} />
      {adminAuthenticated && deliveryAlert && (
        <AlertDeliveryPanel alertId={deliveryAlert.id} title={alertTitle(deliveryAlert)}
          refreshKey={refreshKey} onClose={() => {
            setDeliveryAlert(null);
            document.getElementById(`delivery-${deliveryAlert.id}`)?.focus();
          }} />
      )}
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
      {updateError && <div role="alert"><ErrorState message={t(updateError)} retry={() => { clearUpdateError(); load(); }} /></div>}
      {targetLoading && <LoadingState label={t("Verlinkte Warnung wird geladen")} />}
      {targetError && (
        <ErrorState message={targetError} retry={() => setTargetReloadKey((value) => value + 1)} />
      )}
      {outsideAlert && (
        <section className="surface linked-alert-context">
          <SectionHeader
            title={t("Verlinkte Warnung")}
            subtitle={outsideAlert.historical
              ? t("Gespeichertes Ereignis aus der Historie.")
              : t("Dieses Ereignis liegt außerhalb der aktuellen Filter.")}
          />
          {renderAlertTable([outsideAlert])}
        </section>
      )}
      <section className="surface">
        {loading ? (
          <LoadingState label={t("Warnungen werden bewertet")} />
        ) : error ? null : alerts.length ? (
          renderAlertTable(alerts)
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
              {t("Eine Quelle mit echtem DMARC-Fail. Die Dienstzuordnung ist keine Sendefreigabe.")}
            </span>
          </div>
        </article>
        <article className="logic-item">
          <Info aria-hidden="true" />
          <div>
            <strong>{t("Konfigurationshinweis")}</strong>
            <span>
              {t(
                "Ein Mechanismus ist nicht aligned, DMARC besteht aber weiterhin. Jede betroffene Nachricht zählt einmal; die Gesamtzahl umfasst diese Domain, Source-IP und diesen Reporttag.",
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
