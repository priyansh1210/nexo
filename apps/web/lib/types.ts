// The shapes the API returns (apps/api).
// shortcut: kept by hand, so they can drift from the API; generate them from the API's OpenAPI
// schema when the API grows or gets a second client.

export type User = { user_id: number; email: string; name: string; role: "viewer" | "csm" | "admin" };

export type Freshness = {
  source: string;
  status: "fresh" | "stale";
  last_updated: string | null;
  expected_every_seconds: number;
  is_stalled: boolean;
  rejected_last_day: number;
};

export type Checks = { passed: number; failed: number; failed_models: string[] };

export type UsageStatus = "ok" | "no_linked_workspace" | "no_recent_usage" | "no_baseline";

export type Account = {
  account_id: string;
  name: string;
  owner_name: string;
  owner_email: string;
  plan: string;
  seats: number;
  arr_usd: number;
  contract_start: string;
  renewal_date: string;
  open_tickets: number;
  usage_change: number | null; // a ratio: -0.4 is a 40% drop
  usage_status: UsageStatus;
  usage_as_of: string | null;
  stale_high_tickets: number;
  overdue_invoices: number;
  risk_usage_drop: boolean;
  risk_stale_ticket: boolean;
  risk_overdue_invoice: boolean;
  is_at_risk: boolean;
};

export type AccountList = { accounts: Account[]; freshness: Freshness[]; checks: Checks };

export type Ticket = {
  ticket_id: string;
  subject: string;
  severity: string;
  status: string;
  is_open: boolean;
  age_days: number;
  created_at: string;
  updated_at: string;
  requester_email: string | null;
};

export type Contact = { contact_id: string; name: string; email: string; role: string; is_active: boolean };

export type Onboarding = {
  kickoff_at: string | null;
  admin_setup_at: string | null;
  team_invited_at: string | null;
  data_import_at: string | null;
  go_live_at: string | null;
  steps_completed: number;
  is_complete: boolean;
};

export type AccountProfile = {
  account: Account;
  usage: { as_of_day: string; events_last_30d: number; events_prior_30d: number } | null;
  onboarding: Onboarding | null;
  tickets: Ticket[];
  contacts: Contact[];
  freshness: Freshness[];
  checks: Checks;
};

export type FeatureUsage = {
  feature: string;
  events_last_30d: number;
  events_prior_30d: number;
  usage_change: number | null;
  users_last_30d: number;
  users_prior_30d: number;
};

export type UsageByFeature = {
  account_id: string;
  usage_status: UsageStatus;
  as_of_day: string | null;
  features: FeatureUsage[];
  daily: { day: string; feature: string; events: number }[];
  freshness: Freshness[];
  checks: Checks;
};

export type Note = { note_id: number; account_id: string; body: string; created_at: string; author_name: string };

export type Task = {
  task_id: number;
  account_id: string;
  title: string;
  detail: string;
  status: "open" | "done";
  assignee_email: string | null;
  assignee_name: string | null;
  due_on: string | null;
  created_by_name: string;
  created_by_email: string;
  conversation_id: string | null;
  created_at: string;
  updated_at: string;
};

export type AuditEvent = {
  event_id: number;
  at: string;
  actor_email: string | null;
  actor_name: string | null;
  action: string;
  account_id: string | null;
  target_type: string | null;
  target_id: string | null;
  detail: Record<string, unknown>;
};

export type CheckResult = { model: string; test: string; status: string; failures: number | null; checked_at: string };

export type Claim = { text: string; evidence: string[] };

export type SourceState = {
  source: string;
  label: string;
  status: "fresh" | "stale";
  last_updated: string | null;
  age_hours: number | null;
  rejected_last_day?: number;
};

export type Evidence = {
  tool: string;
  model?: string;
  records?: string[];
  link?: string | null;
  sources: SourceState[];
};

export type ProposalStatus = "pending" | "done" | "rejected" | "refused" | "blocked";

export type Proposal = {
  proposal_id: number;
  conversation_id: string;
  action: "send_email" | "create_task" | "add_note";
  account_id: string;
  params: Record<string, string | null>;
  status: ProposalStatus;
  outcome: { reason?: string; changes?: string[]; email_id?: number; task_id?: number; note_id?: number };
  created_at: string;
  decided_at: string | null;
};

export type Answer = {
  summary: string;
  observations: Claim[];
  hypotheses: Claim[];
  data_notes: string[];
  evidence: Record<string, Evidence>;
  tool_calls: { id: string; name: string; args: Record<string, unknown> }[];
  dropped_claims: { text: string; reason: string }[];
  proposals: Proposal[];
};

export type HistoryEntry = { question: string; summary: string };
