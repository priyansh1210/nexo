// Formatting shared by every screen, so a date or a percent reads the same everywhere.

const day = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" });
const dayTime = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});
const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const whole = new Intl.NumberFormat("en-US");

export const formatDate = (iso: string) => day.format(new Date(iso));
export const formatDateTime = (iso: string) => dayTime.format(new Date(iso));
export const formatMoney = (usd: number) => money.format(usd);
export const formatNumber = (n: number) => whole.format(n);

/** -0.4 becomes "−40%", 0.125 becomes "+12.5%". A true minus sign keeps columns aligned. */
export function formatChange(ratio: number): string {
  const percent = Math.round(ratio * 1000) / 10;
  const sign = percent > 0 ? "+" : percent < 0 ? "−" : "";
  return `${sign}${Math.abs(percent)}%`;
}

/** "3 h ago", "2 days ago": how old a source's data is. */
export function ago(iso: string | null, now = Date.now()): string {
  if (!iso) return "never";
  const hours = (now - new Date(iso).getTime()) / 3_600_000;
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))} min ago`;
  if (hours < 48) return `${Math.round(hours)} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

export function daysUntil(iso: string, now = Date.now()): number {
  return Math.round((new Date(iso).getTime() - now) / 86_400_000);
}

export const SOURCE_LABELS: Record<string, string> = {
  crm: "CRM",
  product_events: "Usage",
  support_tickets: "Support tickets",
  billing: "Billing",
  documents: "Notes and emails",
};

export const USAGE_STATUS_TEXT: Record<string, string> = {
  no_linked_workspace: "No linked workspace",
  no_recent_usage: "No recent usage",
  no_baseline: "No earlier usage to compare",
};

export const TOOL_LABELS: Record<string, string> = {
  list_renewals: "Renewals",
  find_account: "Account search",
  get_account: "Account",
  get_usage: "Usage",
  get_tickets: "Tickets",
  get_onboarding: "Onboarding",
  search_documents: "Notes and emails",
  get_freshness: "Data freshness",
  draft_email: "Email draft",
  draft_task: "Task draft",
  draft_note: "Note draft",
};
