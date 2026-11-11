import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense, type ReactNode } from "react";

import { DataStatus } from "@/components/data-status";
import { TaskToggle } from "@/components/task-toggle";
import { UsageChart } from "@/components/usage-chart";
import { ApiError, api } from "@/lib/api";
import {
  daysUntil,
  formatChange,
  formatDate,
  formatDateTime,
  formatMoney,
  formatNumber,
  USAGE_STATUS_TEXT,
} from "@/lib/format";
import type { AccountProfile, Note, Onboarding, Task, UsageByFeature, User } from "@/lib/types";

import { NoteForm, TaskForm } from "./forms";

export const metadata: Metadata = { title: "Account" };

export default function AccountPage({ params }: PageProps<"/accounts/[id]">) {
  return (
    <>
      <nav aria-label="Breadcrumb" className="text-sm">
        <Link href="/accounts" className="link">
          Accounts
        </Link>
      </nav>
      <Suspense fallback={<p className="mt-6 text-sm text-ink-2">Loading the account…</p>}>
        <Profile params={params} />
      </Suspense>
    </>
  );
}

async function Profile({ params }: Pick<PageProps<"/accounts/[id]">, "params">) {
  const { id } = await params;
  const path = `/accounts/${encodeURIComponent(id)}`;
  let data: [AccountProfile, UsageByFeature, Note[], Task[], User];
  try {
    data = await Promise.all([
      api<AccountProfile>(path),
      api<UsageByFeature>(`${path}/usage`),
      api<Note[]>(`${path}/notes`),
      api<Task[]>(`${path}/tasks`),
      api<User>("/auth/me"),
    ]);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }
  const [profile, usage, notes, tasks, me] = data;
  const { account } = profile;
  const canWrite = me.role !== "viewer";
  const days = daysUntil(account.renewal_date);
  const usageStale = profile.freshness.some((s) => s.source === "product_events" && s.status !== "fresh");

  const risks = [
    account.risk_usage_drop &&
      account.usage_change !== null &&
      (usageStale && account.usage_as_of
        ? `usage fell ${formatChange(account.usage_change).replace("−", "")} in the 30 days to ${formatDate(account.usage_as_of)} (usage data is late)`
        : `usage fell ${formatChange(account.usage_change).replace("−", "")} in 30 days`),
    account.risk_stale_ticket && `${account.stale_high_tickets} high-severity ticket${account.stale_high_tickets === 1 ? "" : "s"} open over 14 days`,
    account.risk_overdue_invoice && `${account.overdue_invoices} overdue invoice${account.overdue_invoices === 1 ? "" : "s"}`,
  ].filter(Boolean);

  return (
    <div className="mt-3 space-y-8">
      <header className="space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
          <h1 className="text-[28px] font-semibold leading-tight">{account.name}</h1>
          <Link href={`/chat?ask=${encodeURIComponent(`Investigate ${account.name}.`)}`} className="button">
            Investigate in chat
          </Link>
        </div>
        <p className="text-ink-2 tabular-nums">
          <span className="capitalize">{account.plan}</span> · {formatNumber(account.seats)} seats · {formatMoney(account.arr_usd)} a year · owned by{" "}
          {account.owner_name}
        </p>
        <p className="tabular-nums">
          Renews {formatDate(account.renewal_date)}
          <span className="text-ink-2"> · {days >= 0 ? `in ${days} days` : `${-days} days ago`}</span>
        </p>
        <p>
          {account.is_at_risk ? (
            <>
              <span className="font-semibold">At risk:</span> {risks.join("; ")}.
            </>
          ) : (
            <span className="text-ink-2">No risk signals in the data.</span>
          )}
        </p>
        <DataStatus freshness={profile.freshness} checks={profile.checks} />
      </header>

      <div className="grid gap-x-12 gap-y-10 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 space-y-10">
          <Section title="Usage by feature" note={usage.as_of_day ? `30 days to ${formatDate(usage.as_of_day)}` : undefined}>
            {usageStale && (
              <p className="mb-3 text-sm text-stale">Usage data is late, so these figures may be out of date.</p>
            )}
            {usage.usage_status !== "ok" || !usage.features.length ? (
              <p className="text-sm text-ink-2">
                {USAGE_STATUS_TEXT[usage.usage_status] ?? "No usage recorded yet"}. This is not the same as zero use.
              </p>
            ) : (
              <UsageChart features={usage.features} />
            )}
          </Section>

          <Section title="Tickets" note={`${account.open_tickets} open`}>
            {profile.tickets.length === 0 ? (
              <p className="text-sm text-ink-2">No support tickets.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="table">
                  <thead>
                    <tr>
                      <th scope="col">Subject</th>
                      <th scope="col" className="hidden sm:table-cell">
                        Severity
                      </th>
                      <th scope="col" className="hidden sm:table-cell">
                        Status
                      </th>
                      <th scope="col" className="num hidden sm:table-cell">
                        Age
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {profile.tickets.map((ticket) => (
                      <tr key={ticket.ticket_id} className={ticket.is_open ? undefined : "text-ink-2"}>
                        <td>
                          {ticket.subject}
                          <span className="block text-[13px] text-ink-2 sm:hidden">
                            <span className="capitalize">{ticket.severity}</span> · {ticket.status} · {ticket.age_days}{" "}
                            days
                          </span>
                          <span className="block font-mono text-[12px] text-ink-2">{ticket.ticket_id}</span>
                        </td>
                        <td className="hidden capitalize sm:table-cell">{ticket.severity}</td>
                        <td className="hidden capitalize sm:table-cell">{ticket.status}</td>
                        <td className="num hidden whitespace-nowrap sm:table-cell">{ticket.age_days} days</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>

          <Section title="Onboarding">
            <OnboardingSteps onboarding={profile.onboarding} />
          </Section>
        </div>

        <div className="min-w-0 space-y-10">
          <Section title="Contacts">
            {profile.contacts.length === 0 ? (
              <p className="text-sm text-ink-2">No contacts in the CRM.</p>
            ) : (
              <ul className="space-y-2 text-sm">
                {profile.contacts.map((contact) => (
                  <li key={contact.contact_id}>
                    <span className="font-medium">{contact.name}</span>
                    <span className="text-ink-2"> · {contact.role}</span>
                    <span className="block text-ink-2">{contact.email}</span>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section title="Tasks">
            {tasks.length === 0 && <p className="mb-3 text-sm text-ink-2">No tasks on this account.</p>}
            <ul className="mb-4 space-y-3 text-sm">
              {tasks.map((task) => (
                <li key={task.task_id} className="flex items-start justify-between gap-3">
                  <span className={task.status === "done" ? "text-ink-2 line-through" : undefined}>
                    {task.title}
                    <span className="block text-[13px] text-ink-2 no-underline">
                      {task.assignee_name ?? "Unassigned"}
                      {task.due_on && ` · due ${formatDate(task.due_on)}`}
                    </span>
                  </span>
                  {canWrite && <TaskToggle taskId={task.task_id} status={task.status} title={task.title} />}
                </li>
              ))}
            </ul>
            {canWrite && <TaskForm accountId={account.account_id} defaultAssignee={account.owner_email} />}
          </Section>

          <Section title="Notes">
            {canWrite && <NoteForm accountId={account.account_id} />}
            {notes.length === 0 ? (
              <p className="mt-3 text-sm text-ink-2">No notes yet.</p>
            ) : (
              <ul className="mt-4 space-y-4 text-sm">
                {notes.map((note) => (
                  <li key={note.note_id}>
                    <p className="whitespace-pre-line leading-relaxed">{note.body}</p>
                    <p className="mt-0.5 text-[13px] text-ink-2">
                      {note.author_name} · {formatDateTime(note.created_at)}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </Section>
        </div>
      </div>
    </div>
  );
}

function Section({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section aria-label={title}>
      <h2 className="flex items-baseline justify-between gap-4 border-b border-rule pb-2">
        <span className="font-semibold">{title}</span>
        {note && <span className="text-[13px] font-normal text-ink-2 tabular-nums">{note}</span>}
      </h2>
      <div className="mt-4">{children}</div>
    </section>
  );
}

const STEPS: { key: keyof Onboarding; label: string }[] = [
  { key: "kickoff_at", label: "Kickoff" },
  { key: "admin_setup_at", label: "Admin set up" },
  { key: "team_invited_at", label: "Team invited" },
  { key: "data_import_at", label: "Data imported" },
  { key: "go_live_at", label: "Live" },
];

function OnboardingSteps({ onboarding }: { onboarding: Onboarding | null }) {
  if (!onboarding) return <p className="text-sm text-ink-2">No onboarding data: the account has no linked workspace.</p>;
  return (
    <ol className="space-y-0 text-sm">
      {STEPS.map(({ key, label }, index) => {
        const at = onboarding[key] as string | null;
        const last = index === STEPS.length - 1;
        return (
          <li key={key} className="grid grid-cols-[1rem_minmax(0,1fr)] gap-3">
            <span className="flex flex-col items-center" aria-hidden="true">
              <span className={`mt-1.5 size-2.5 rounded-full border-2 ${at ? "border-accent bg-accent" : "border-ink-2/50"}`} />
              {!last && <span className="w-px flex-1 bg-rule" />}
            </span>
            <span className={last ? "" : "pb-4"}>
              <span className={at ? "font-medium" : "text-ink-2"}>{label}</span>
              <span className="block text-[13px] text-ink-2 tabular-nums">{at ? formatDate(at) : "Not reached"}</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}
