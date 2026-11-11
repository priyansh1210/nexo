"use client";

import Link from "next/link";

import { Icon } from "@/components/icons";
import { daysUntil, formatDate, formatMoney, TOOL_LABELS } from "@/lib/format";
import type { Account, Answer, Claim } from "@/lib/types";

import { ApprovalCard } from "./approval-card";

export type OpenSource = (callId: string, chip: HTMLElement) => void;

/** A source's footnote number: its place in the order the tools were called. */
export function sourceNumber(answer: Answer, callId: string): number {
  return answer.tool_calls.findIndex((call) => call.id === callId) + 1;
}

export function AnswerView({
  answer,
  accounts,
  openSource,
}: {
  answer: Answer;
  accounts: Account[];
  openSource: OpenSource;
}) {
  // An observation that only repeats the lead sentence is shown once: its sources move to the lead.
  const repeated = answer.observations.find((claim) => answer.summary.startsWith(claim.text));
  const observations = answer.observations.filter((claim) => claim !== repeated);
  return (
    <div className="space-y-5">
      {answer.data_notes.length > 0 && <DataNotes notes={answer.data_notes} />}
      <p className="text-[18px] font-medium leading-snug">
        {answer.summary}
        {repeated?.evidence.map((callId) => (
          <SourceChip key={callId} number={sourceNumber(answer, callId)} onOpen={(chip) => openSource(callId, chip)} />
        ))}
      </p>
      {accounts.length > 0 && <AccountsInline accounts={accounts} />}
      {observations.length > 0 && (
        <section aria-label="Observed">
          <h3 className="label">Observed</h3>
          <Claims claims={observations} answer={answer} openSource={openSource} />
        </section>
      )}
      {answer.hypotheses.length > 0 && (
        <section aria-label="Possible cause, not confirmed" className="border-l-2 border-dashed border-ink-2/40 pl-4">
          <h3 className="label">Possible cause · not confirmed</h3>
          <Claims claims={answer.hypotheses} answer={answer} openSource={openSource} />
        </section>
      )}
      {answer.dropped_claims.length > 0 && <Dropped dropped={answer.dropped_claims} />}
      {answer.tool_calls.length > 0 && <Trace answer={answer} openSource={openSource} />}
      {answer.proposals.map((proposal) => (
        <ApprovalCard key={proposal.proposal_id} initial={proposal} />
      ))}
    </div>
  );
}

function DataNotes({ notes }: { notes: string[] }) {
  return (
    <div role="note" className="flex gap-2.5 border-l-2 border-stale py-0.5 pl-3 text-sm">
      <Icon name="warning" className="mt-0.5 size-4 shrink-0 text-stale" />
      <ul className="space-y-1">
        {notes.map((note) => (
          <li key={note}>{note}</li>
        ))}
      </ul>
    </div>
  );
}

function Claims({ claims, answer, openSource }: { claims: Claim[]; answer: Answer; openSource: OpenSource }) {
  return (
    <ul className="mt-2 space-y-2">
      {claims.map((claim) => (
        <li key={claim.text} className="leading-relaxed">
          {claim.text}
          {claim.evidence.map((callId) => (
            <SourceChip key={callId} number={sourceNumber(answer, callId)} onOpen={(chip) => openSource(callId, chip)} />
          ))}
        </li>
      ))}
    </ul>
  );
}

export function SourceChip({ number, onOpen }: { number: number; onOpen: (chip: HTMLElement) => void }) {
  return (
    <button
      type="button"
      onClick={(event) => onOpen(event.currentTarget)}
      className="-my-1 ml-0.5 inline-flex min-h-6 min-w-6 items-center justify-center align-baseline text-[13px] font-medium tabular-nums text-accent hover:underline"
      aria-label={`Source ${number}`}
    >
      [{number}]
    </button>
  );
}

function AccountsInline({ accounts }: { accounts: Account[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="table">
        <thead>
          <tr>
            <th scope="col">Account</th>
            <th scope="col">Renews</th>
            <th scope="col">Owner</th>
            <th scope="col" className="num">
              ARR
            </th>
          </tr>
        </thead>
        <tbody>
          {accounts.map((account) => (
            <tr key={account.account_id}>
              <td>
                <Link href={`/accounts/${account.account_id}`} className="link font-medium">
                  {account.name}
                </Link>
              </td>
              <td className="whitespace-nowrap">
                {formatDate(account.renewal_date)}
                <span className="text-ink-2"> · in {daysUntil(account.renewal_date)} days</span>
              </td>
              <td>{account.owner_name}</td>
              <td className="num">{formatMoney(account.arr_usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Dropped({ dropped }: { dropped: Answer["dropped_claims"] }) {
  const count = dropped.length;
  return (
    <details className="text-[13px] text-ink-2">
      <summary className="cursor-pointer">
        {count} {count === 1 ? "statement was" : "statements were"} left out because the data does not support
        {count === 1 ? " it" : " them"}
      </summary>
      <ul className="mt-2 space-y-1.5 pl-4">
        {dropped.map((item) => (
          <li key={item.text}>
            “{item.text}” <span className="whitespace-nowrap">({item.reason})</span>
          </li>
        ))}
      </ul>
    </details>
  );
}

function Trace({ answer, openSource }: { answer: Answer; openSource: OpenSource }) {
  const looked = [...new Set(answer.tool_calls.map((call) => TOOL_LABELS[call.name] ?? call.name))];
  const count = answer.tool_calls.length;
  return (
    <details className="group text-sm">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 text-ink-2 hover:text-ink">
        <Icon name="expand" className="size-4 transition-transform group-open:rotate-180" />
        Checked {looked.join(", ").toLowerCase()} · {count} {count === 1 ? "lookup" : "lookups"}
      </summary>
      <ol className="mt-2 space-y-1 border-l border-rule pl-4">
        {answer.tool_calls.map((call, index) => {
          const args = Object.entries(call.args)
            .map(([key, value]) => `${key}: ${String(value)}`)
            .join(", ");
          return (
            <li key={call.id} className="text-[13px]">
              <SourceChip number={index + 1} onOpen={(chip) => openSource(call.id, chip)} />{" "}
              <span className="font-medium">{TOOL_LABELS[call.name] ?? call.name}</span>
              {args && <span className="text-ink-2"> · {args}</span>}
            </li>
          );
        })}
      </ol>
    </details>
  );
}
