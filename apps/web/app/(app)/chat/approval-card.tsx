"use client";

import Link from "next/link";
import { useState, useTransition } from "react";

import { Icon } from "@/components/icons";
import type { Proposal } from "@/lib/types";

import { decide } from "./actions";

const TITLES: Record<Proposal["action"], string> = {
  send_email: "Send an email",
  create_task: "Create a task",
  add_note: "Add a note",
};

const WHO_MAY: Record<Proposal["action"], string> = {
  send_email: "Only the account's owner or an admin can approve an email.",
  create_task: "A CSM or an admin can approve this.",
  add_note: "A CSM or an admin can approve this.",
};

// The fields a person may change before approving, in the order they read.
const EDITABLE: Record<Proposal["action"], { name: string; label: string; long?: boolean; type?: string }[]> = {
  send_email: [
    { name: "to_email", label: "To", type: "email" },
    { name: "subject", label: "Subject" },
    { name: "body", label: "Message", long: true },
  ],
  create_task: [
    { name: "title", label: "Title" },
    { name: "detail", label: "Detail", long: true },
    { name: "assignee_email", label: "Assignee", type: "email" },
    { name: "due_on", label: "Due", type: "date" },
  ],
  add_note: [{ name: "body", label: "Note", long: true }],
};

export function ApprovalCard({ initial }: { initial: Proposal }) {
  const [proposal, setProposal] = useState(initial);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string>();
  const [pending, startTransition] = useTransition();
  const fields = EDITABLE[proposal.action];

  function send(decision: "approve" | "edit" | "reject", form?: FormData) {
    setError(undefined);
    const changed: Record<string, string | null> = {};
    for (const field of fields) {
      const value = form?.get(field.name);
      if (typeof value === "string" && value !== (proposal.params[field.name] ?? "")) {
        changed[field.name] = value || null;
      }
    }
    const asked = decision === "edit" && !Object.keys(changed).length ? "approve" : decision;
    startTransition(async () => {
      const result = await decide(proposal.proposal_id, asked, changed);
      if ("error" in result) setError(result.error);
      else {
        setProposal(result.proposal);
        setEditing(false);
      }
    });
  }

  const titleId = `proposal-${proposal.proposal_id}`;
  return (
    <section
      aria-labelledby={titleId}
      className="rounded-md border border-rule bg-surface p-4 shadow-[0_1px_2px_rgb(0_0_0/0.06)] sm:p-5"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 id={titleId} className="font-semibold">
          {TITLES[proposal.action]}
        </h3>
        <Link href={`/accounts/${proposal.account_id}`} className="link text-[13px]">
          View account
        </Link>
      </div>

      {proposal.status === "pending" && editing ? (
        <form
          action={(form) => send("edit", form)}
          className="mt-4 space-y-3"
          aria-describedby={error ? `${titleId}-error` : undefined}
        >
          {fields.map((field) => (
            <div key={field.name} className="space-y-1">
              <label htmlFor={`${titleId}-${field.name}`} className="block text-[13px] font-medium">
                {field.label}
              </label>
              {field.long ? (
                <textarea
                  id={`${titleId}-${field.name}`}
                  name={field.name}
                  defaultValue={proposal.params[field.name] ?? ""}
                  rows={field.name === "body" ? 6 : 3}
                  className="field leading-relaxed"
                />
              ) : (
                <input
                  id={`${titleId}-${field.name}`}
                  name={field.name}
                  type={field.type ?? "text"}
                  defaultValue={proposal.params[field.name] ?? ""}
                  className="field"
                />
              )}
            </div>
          ))}
          <Status error={error} id={`${titleId}-error`} />
          <div className="flex flex-wrap gap-2 pt-1">
            <button type="submit" className="button button-primary" disabled={pending}>
              {pending ? "Checking and approving…" : "Approve with changes"}
            </button>
            <button type="button" className="button" disabled={pending} onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <>
          <Draft proposal={proposal} />
          {proposal.status === "pending" ? (
            <>
              <p className="mt-3 text-[13px] text-ink-2">
                Nothing happens until you approve. Nexo then rechecks the live records first.{" "}
                {WHO_MAY[proposal.action]}
              </p>
              <Status error={error} id={`${titleId}-error`} />
              <div className="mt-4 flex flex-wrap gap-2">
                <button type="button" className="button button-primary" disabled={pending} onClick={() => send("approve")}>
                  {pending ? "Checking and approving…" : "Approve"}
                </button>
                <button type="button" className="button" disabled={pending} onClick={() => setEditing(true)}>
                  Edit
                </button>
                <button type="button" className="button" disabled={pending} onClick={() => send("reject")}>
                  Reject
                </button>
              </div>
            </>
          ) : (
            <Receipt proposal={proposal} />
          )}
        </>
      )}
    </section>
  );
}

function Draft({ proposal }: { proposal: Proposal }) {
  const p = proposal.params;
  if (proposal.action === "send_email") {
    return (
      <div className="mt-3 space-y-2 text-sm">
        <p>
          <span className="text-ink-2">To </span>
          {p.to_email}
          {p.ticket_id && <span className="text-ink-2"> · about ticket {p.ticket_id}</span>}
        </p>
        <p className="font-medium">{p.subject}</p>
        <p className="whitespace-pre-line leading-relaxed text-ink-2">{p.body}</p>
      </div>
    );
  }
  if (proposal.action === "create_task") {
    return (
      <div className="mt-3 space-y-1 text-sm">
        <p className="font-medium">{p.title}</p>
        {p.detail && <p className="text-ink-2">{p.detail}</p>}
        <p className="text-ink-2">
          {p.assignee_email ? `Assigned to ${p.assignee_email}` : "Unassigned"}
          {p.due_on && ` · due ${p.due_on}`}
        </p>
      </div>
    );
  }
  return <p className="mt-3 whitespace-pre-line text-sm leading-relaxed">{p.body}</p>;
}

function Status({ error, id }: { error?: string; id: string }) {
  return (
    <p id={id} role="alert" className="mt-3 text-sm text-failed empty:hidden">
      {error}
    </p>
  );
}

function Receipt({ proposal }: { proposal: Proposal }) {
  const trail = `/audit?target_type=proposal&target_id=${proposal.proposal_id}`;
  const { outcome } = proposal;
  const done = proposal.status === "done";
  const message = {
    done:
      proposal.action === "send_email"
        ? `Approved. The email is queued and goes out within a minute.`
        : proposal.action === "create_task"
          ? "Approved. The task is created."
          : "Approved. The note is added.",
    blocked: "Not done: the live records changed since the draft.",
    refused: `Not allowed. ${outcome.reason ?? ""}`,
    rejected: "Rejected. Nothing was done.",
    pending: "",
  }[proposal.status];
  return (
    <div role="status" className="mt-4 border-t border-rule pt-3 text-sm">
      <p className={`flex items-start gap-2 ${done ? "" : proposal.status === "rejected" ? "text-ink-2" : "text-failed"}`}>
        <Icon
          name={done ? "done" : proposal.status === "rejected" ? "close" : "warning"}
          className={`mt-0.5 size-4 shrink-0 ${done ? "text-fresh" : ""}`}
        />
        <span>{message}</span>
      </p>
      {outcome.changes && (
        <ul className="mt-2 list-disc space-y-1 pl-10 text-ink">
          {outcome.changes.map((change) => (
            <li key={change}>{change}</li>
          ))}
        </ul>
      )}
      <p className="mt-2 pl-6">
        <Link href={trail} className="link inline-flex items-center gap-1 text-[13px]">
          Audit trail <Icon name="external" className="size-3.5" />
        </Link>
      </p>
    </div>
  );
}
