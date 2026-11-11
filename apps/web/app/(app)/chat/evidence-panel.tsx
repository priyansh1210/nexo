"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";

import { Icon } from "@/components/icons";
import { ago, TOOL_LABELS } from "@/lib/format";
import type { Answer } from "@/lib/types";

import { sourceNumber } from "./answer";

export type Opened = { answer: Answer; callId: string };

export function EvidencePanel({ opened, onClose }: { opened: Opened; onClose: () => void }) {
  const heading = useRef<HTMLHeadingElement>(null);
  const { answer, callId } = opened;
  const evidence = answer.evidence[callId];
  const call = answer.tool_calls.find((c) => c.id === callId);
  const number = sourceNumber(answer, callId);
  const citing = [...answer.observations, ...answer.hypotheses].filter((claim) => claim.evidence.includes(callId));

  useEffect(() => {
    heading.current?.focus();
    const close = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [callId, onClose]);

  if (!evidence || !call) return null;
  const records = evidence.records ?? [];
  const accountLinks = evidence.link?.startsWith("/accounts/") || call.name === "list_renewals";

  return (
    <aside
      aria-labelledby="evidence-heading"
      className="fixed inset-x-0 bottom-0 z-40 max-h-[70dvh] overflow-y-auto rounded-t-lg border-t border-rule bg-surface p-5 shadow-[0_-8px_24px_rgb(0_0_0/0.12)] motion-safe:animate-[rise_150ms_ease-out] min-[1100px]:sticky min-[1100px]:top-6 min-[1100px]:max-h-[calc(100dvh-3rem)] min-[1100px]:rounded-md min-[1100px]:border min-[1100px]:shadow-none"
    >
      <div className="flex items-start justify-between gap-4">
        <h2 id="evidence-heading" ref={heading} tabIndex={-1} className="text-lg font-semibold outline-none">
          {TOOL_LABELS[call.name] ?? call.name}{" "}
          <span className="font-medium tabular-nums text-ink-2">[{number}]</span>
        </h2>
        <button type="button" onClick={onClose} className="text-ink-2 hover:text-ink" aria-label="Close source">
          <Icon name="close" className="size-5" />
        </button>
      </div>

      <dl className="mt-4 space-y-3 text-sm">
        {evidence.sources.length > 0 && (
          <div>
            <dt className="label">Data behind it</dt>
            <dd className="mt-1 space-y-1">
              {evidence.sources.map((source) => (
                <p key={source.source} className="flex items-center gap-2">
                  <span
                    aria-hidden="true"
                    className={`size-2 shrink-0 rounded-full ${source.status === "fresh" ? "bg-fresh" : "bg-stale"}`}
                  />
                  <span>
                    {source.label}
                    <span className={source.status === "fresh" ? "text-ink-2" : "text-stale"}>
                      {" "}
                      · {source.status === "fresh" ? "updated" : "stale, last updated"} {ago(source.last_updated)}
                    </span>
                  </span>
                </p>
              ))}
            </dd>
          </div>
        )}
        {evidence.model && (
          <div>
            <dt className="label">Warehouse table</dt>
            <dd className="mt-1 font-mono text-[13px]">{evidence.model}</dd>
          </div>
        )}
        {records.length > 0 && (
          <div>
            <dt className="label">Records</dt>
            <dd className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[13px]">
              {records.map((record) =>
                accountLinks && record.startsWith("acct_") ? (
                  <Link key={record} href={`/accounts/${record}`} className="link">
                    {record}
                  </Link>
                ) : (
                  <span key={record} className="font-mono">
                    {record}
                  </span>
                ),
              )}
            </dd>
          </div>
        )}
        {citing.length > 0 && (
          <div>
            <dt className="label">Cited by</dt>
            <dd className="mt-1 space-y-1.5">
              {citing.map((claim) => (
                <p key={claim.text}>{claim.text}</p>
              ))}
            </dd>
          </div>
        )}
      </dl>

      {evidence.link && (
        <Link href={evidence.link} className="link mt-5 inline-flex items-center gap-1 text-sm font-medium">
          Open the account <Icon name="external" className="size-3.5" />
        </Link>
      )}
    </aside>
  );
}
