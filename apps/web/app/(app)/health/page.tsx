import type { Metadata } from "next";
import { Suspense } from "react";

import { Icon } from "@/components/icons";
import { api } from "@/lib/api";
import { ago, formatDateTime, SOURCE_LABELS } from "@/lib/format";
import type { CheckResult, Freshness, User } from "@/lib/types";

export const metadata: Metadata = { title: "Data health" };

export default function HealthPage() {
  return (
    <>
      <h1 className="text-[22px] font-semibold">Data health</h1>
      <p className="mt-1 max-w-2xl text-sm text-ink-2">
        The assistant reads only what is shown here. A late source or a failed check narrows what it will state, and it
        says so in the answer.
      </p>
      <Suspense fallback={<p className="mt-6 text-sm text-ink-2">Loading data health…</p>}>
        <Health />
      </Suspense>
    </>
  );
}

async function Health() {
  const [sources, checks, me] = await Promise.all([
    api<Freshness[]>("/freshness"),
    api<CheckResult[]>("/checks"),
    api<User>("/auth/me"),
  ]);
  const failed = checks.filter((check) => check.status === "fail" || check.status === "error");
  const passed = checks.filter((check) => check.status === "pass").length;

  return (
    <div className="mt-8 space-y-12">
      <section aria-label="Sources">
        <h2 className="border-b border-rule pb-2 font-semibold">Sources</h2>
        {sources.length === 0 ? (
          <p className="mt-4 text-sm text-ink-2">No source has synced yet. The first pipeline run loads them.</p>
        ) : (
          <div className="mt-4 overflow-x-auto">
            <table className="table min-w-[640px]">
              <thead>
                <tr>
                  <th scope="col">Source</th>
                  <th scope="col">Status</th>
                  <th scope="col">Last updated</th>
                  <th scope="col">Expected every</th>
                  <th scope="col" className="num">
                    Set aside, last day
                  </th>
                </tr>
              </thead>
              <tbody>
                {sources.map((source) => (
                  <tr key={source.source}>
                    <td className="font-medium">{SOURCE_LABELS[source.source] ?? source.source}</td>
                    <td>
                      <span className={`inline-flex items-center gap-2 ${source.status === "fresh" ? "" : "text-stale"}`}>
                        <span
                          aria-hidden="true"
                          className={`size-2 rounded-full ${source.status === "fresh" ? "bg-fresh" : "bg-stale"}`}
                        />
                        {source.status === "fresh" ? "Up to date" : "Late"}
                        {source.is_stalled && <span className="text-[13px] text-ink-2">(paused for a demo)</span>}
                      </span>
                    </td>
                    <td className="whitespace-nowrap">
                      {ago(source.last_updated)}
                      {source.last_updated && (
                        <span className="block text-[13px] text-ink-2">{formatDateTime(source.last_updated)}</span>
                      )}
                    </td>
                    <td>{hours(source.expected_every_seconds)}</td>
                    <td className="num">
                      {source.rejected_last_day > 0 ? (
                        <span className="text-stale">{source.rejected_last_day}</span>
                      ) : (
                        <span className="text-ink-2">0</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-[13px] text-ink-2">
              A source is late once twice its expected interval has passed. Records that could not be read are set aside
              instead of stopping the source, and counted here.
            </p>
          </div>
        )}
      </section>

      <section aria-label="Warehouse checks">
        <h2 className="flex items-baseline justify-between gap-4 border-b border-rule pb-2">
          <span className="font-semibold">Warehouse checks</span>
          <span className="text-[13px] text-ink-2 tabular-nums">
            {passed} passed · {failed.length} failed
          </span>
        </h2>
        {checks.length === 0 ? (
          <p className="mt-4 text-sm text-ink-2">The warehouse has not been built yet.</p>
        ) : (
          <>
            {failed.length === 0 ? (
              <p className="mt-4 flex items-center gap-2 text-sm">
                <Icon name="done" className="size-4 text-fresh" />
                Every check passed on the last build.
              </p>
            ) : (
              <ul className="mt-4 space-y-2 text-sm">
                {failed.map((check) => (
                  <li key={`${check.model}-${check.test}`} className="flex items-start gap-2">
                    <Icon name="warning" className="mt-0.5 size-4 shrink-0 text-failed" />
                    <span>
                      <span className="font-medium">{check.model}</span>: {check.test}
                      {check.failures !== null && (
                        <span className="text-ink-2"> · {check.failures} failing rows</span>
                      )}
                      <span className="block text-[13px] text-ink-2">
                        The assistant leaves out the figures built on this model until it passes.
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <details className="mt-4">
              <summary className="link cursor-pointer text-sm">All {checks.length} checks</summary>
              <div className="mt-3 overflow-x-auto">
                <table className="table min-w-[560px]">
                  <thead>
                    <tr>
                      <th scope="col">Model</th>
                      <th scope="col">Check</th>
                      <th scope="col">Result</th>
                    </tr>
                  </thead>
                  <tbody>
                    {checks.map((check) => (
                      <tr key={`${check.model}-${check.test}`}>
                        <td className="font-mono text-[13px]">{check.model}</td>
                        <td className="text-[13px]">{check.test}</td>
                        <td className={check.status === "pass" ? "text-ink-2" : "font-medium text-failed"}>{check.status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          </>
        )}
      </section>

      {/* shortcut: admins are shown the command, not a button; add an admin API route that queues a
          Dagster replay run when admins should rebuild without server access. */}
      {me.role === "admin" && (
        <section aria-label="Rebuild">
          <h2 className="border-b border-rule pb-2 font-semibold">Rebuild</h2>
          <p className="mt-4 max-w-2xl text-sm">
            To rebuild the whole warehouse from the raw data, run <code className="font-mono text-[13px]">make replay</code>{" "}
            on the server. Raw data is never changed, so a rebuild gives the same results.
          </p>
        </section>
      )}
    </div>
  );
}

function hours(seconds: number): string {
  const h = seconds / 3600;
  return h >= 24 ? `${h / 24} day${h === 24 ? "" : "s"}` : `${h} hour${h === 1 ? "" : "s"}`;
}
