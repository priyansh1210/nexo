import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { ApiError, api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { AuditEvent } from "@/lib/types";

export const metadata: Metadata = { title: "Audit" };

// What to show: an action prefix the API filters on ("action." means every action.* event).
const KINDS = {
  "": "Everything",
  "action.": "Assistant actions",
  "email.": "Email delivery",
  "task.": "Tasks",
  "note.": "Notes",
  "auth.login": "Sign-ins",
  "ingest.": "Data pushed in",
} as const;

const ACTIONS: Record<string, string> = {
  send_email: "the email",
  create_task: "the task",
  add_note: "the note",
};

export default function AuditPage({ searchParams }: PageProps<"/audit">) {
  return (
    <>
      <h1 className="text-[22px] font-semibold">Audit log</h1>
      <p className="mt-1 text-sm text-ink-2">Every change in Nexo, newest first. Rows cannot be edited or deleted.</p>
      <Suspense fallback={<p className="mt-6 text-sm text-ink-2">Loading the audit log…</p>}>
        <Audit searchParams={searchParams} />
      </Suspense>
    </>
  );
}

async function Audit({ searchParams }: Pick<PageProps<"/audit">, "searchParams">) {
  const params = await searchParams;
  const text = (key: string) => (typeof params[key] === "string" ? (params[key] as string).trim() : "");
  const kind = text("kind") in KINDS ? text("kind") : "";
  const account = text("account");
  const [targetType, targetId] = [text("target_type"), text("target_id")];

  const query = new URLSearchParams({ limit: "200" });
  if (kind) query.set("action", kind);
  if (account) query.set("account_id", account);
  if (targetType && targetId) {
    query.set("target_type", targetType);
    query.set("target_id", targetId);
  }

  let events: AuditEvent[];
  try {
    events = await api<AuditEvent[]>(`/audit?${query}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) {
      return <p className="mt-6 text-sm">The audit log is open to CSMs and admins. Ask one of them if you need a record.</p>;
    }
    throw error;
  }

  return (
    <div className="mt-6 space-y-5">
      {targetType && targetId ? (
        <p className="text-sm">
          The trail for {targetType} {targetId}.{" "}
          <Link href="/audit" className="link">
            Show everything
          </Link>
        </p>
      ) : (
        <form className="flex flex-wrap items-end gap-3" role="search" aria-label="Filter the audit log">
          <div>
            <label htmlFor="kind" className="block text-[13px] text-ink-2">
              Show
            </label>
            <select id="kind" name="kind" defaultValue={kind} className="field mt-1 w-auto pr-8">
              {Object.entries(KINDS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="account" className="block text-[13px] text-ink-2">
              Account id
            </label>
            <input id="account" name="account" defaultValue={account} placeholder="acct_acme" className="field mt-1 w-44" />
          </div>
          <button type="submit" className="button">
            Filter
          </button>
          {(kind || account) && (
            <Link href="/audit" className="link pb-2 text-sm">
              Clear
            </Link>
          )}
        </form>
      )}

      {events.length === 0 ? (
        <p className="text-sm text-ink-2">Nothing matches.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="table min-w-[820px]">
            <thead>
              <tr>
                <th scope="col">When</th>
                <th scope="col">Who</th>
                <th scope="col">What</th>
                <th scope="col">Account</th>
                <th scope="col">Details</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr key={event.event_id}>
                  <td className="whitespace-nowrap">{formatDateTime(event.at)}</td>
                  <td>{who(event)}</td>
                  <td>
                    {event.target_type === "proposal" && !targetId ? (
                      <Link
                        href={`/audit?target_type=proposal&target_id=${event.target_id}`}
                        className="link"
                        title="Show this action's whole trail"
                      >
                        {what(event)}
                      </Link>
                    ) : (
                      what(event)
                    )}
                  </td>
                  <td>
                    {event.account_id ? (
                      <Link href={`/accounts/${event.account_id}`} className="link">
                        {event.account_id}
                      </Link>
                    ) : (
                      <span className="sr-only">No account</span>
                    )}
                  </td>
                  <td className="max-w-[360px] text-[13px] text-ink-2">{details(event)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {events.length === 200 && <p className="text-[13px] text-ink-2">Showing the newest 200. Filter to see older rows.</p>}
    </div>
  );
}

function who(event: AuditEvent): string {
  if (event.actor_name) return event.actor_name;
  const pushedBy = event.detail.pushed_by;
  if (typeof pushedBy === "string") return pushedBy;
  return event.action.startsWith("email.") ? "Nexo's mail sender" : "Nexo";
}

function what(event: AuditEvent): string {
  const subject = ACTIONS[String(event.detail.action)] ?? "an action";
  const verbs: Record<string, string> = {
    "action.proposed": `The assistant drafted ${subject}`,
    "action.approved": `Approved ${subject}`,
    "action.executed": `Carried out ${subject}`,
    "action.verified": `Checked ${subject} took effect`,
    "action.refused": `Not allowed: ${subject}`,
    "action.blocked": `Stopped ${subject}: records changed`,
    "action.rejected": `Rejected ${subject}`,
    "email.sent": "Email sent",
    "email.logged": "Email logged, not sent (no mail server set)",
    "email.retry": "Email send failed; will retry",
    "email.failed": "Email failed after 5 tries",
    "task.created": "Created a task",
    "task.updated": "Changed a task",
    "note.created": "Added a note",
    "auth.login": "Signed in",
    "user.created": "Added a user",
    "api_key.created": "Created an API key",
    "api_key.revoked": "Revoked an API key",
  };
  if (event.action.startsWith("ingest.")) return `Pushed ${event.action.slice(7).replace("_", " ")} in`;
  return verbs[event.action] ?? event.action;
}

function details(event: AuditEvent): string {
  const d = event.detail as Record<string, unknown>;
  const parts: string[] = [];
  if (d.before && d.after && typeof d.before === "object" && typeof d.after === "object") {
    const before = d.before as Record<string, unknown>;
    const after = d.after as Record<string, unknown>;
    for (const key of Object.keys(after)) {
      if (before[key] !== after[key]) parts.push(`${key.replace("_", " ")}: ${before[key] ?? "none"} → ${after[key] ?? "none"}`);
    }
  }
  const params = (d.params ?? {}) as Record<string, unknown>;
  for (const key of ["to_email", "subject", "title"] as const) if (params[key]) parts.push(String(params[key]));
  if (typeof d.reason === "string") parts.push(d.reason);
  if (Array.isArray(d.changes)) parts.push(...d.changes.map(String));
  if (Array.isArray(d.edited) && d.edited.length) parts.push(`edited: ${d.edited.join(", ")}`);
  if (typeof d.to === "string") parts.push(`to ${d.to}`);
  if (typeof d.error === "string") parts.push(d.error);
  if (typeof d.records === "number") parts.push(`${d.records} records`);
  if (typeof d.title === "string") parts.push(d.title);
  if (typeof d.email === "string") parts.push(d.email);
  return parts.join(" · ");
}
