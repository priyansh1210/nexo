import Link from "next/link";

import { Icon } from "@/components/icons";
import { ago, SOURCE_LABELS } from "@/lib/format";
import type { Checks, Freshness } from "@/lib/types";

/** How far the data on this screen can be trusted: one quiet line when all is well. */
export function DataStatus({ freshness, checks }: { freshness: Freshness[]; checks: Checks }) {
  const stale = freshness.filter((source) => source.status !== "fresh");
  const rejected = freshness.filter((source) => source.rejected_last_day > 0);

  if (!stale.length && !checks.failed && !rejected.length) {
    return (
      <p className="text-[13px] text-ink-2">
        <span className="mr-2 inline-block size-2 rounded-full bg-fresh align-middle" aria-hidden="true" />
        All sources are up to date and {checks.passed} warehouse checks passed.{" "}
        <Link href="/health" className="link whitespace-nowrap">
          Data health
        </Link>
      </p>
    );
  }
  return (
    <div role="note" className="flex gap-2.5 border-l-2 border-stale py-0.5 pl-3 text-sm">
      <Icon name="warning" className="mt-0.5 size-4 shrink-0 text-stale" />
      <ul className="space-y-1">
        {stale.map((source) => (
          <li key={source.source}>
            {SOURCE_LABELS[source.source] ?? source.source} data{" "}
            {source.last_updated ? `last updated ${ago(source.last_updated)}` : "has never been loaded"}, so its
            figures may be out of date.
          </li>
        ))}
        {checks.failed > 0 && (
          <li>
            A warehouse check failed on {checks.failed_models.join(", ")}; figures built on it should not be trusted.
          </li>
        )}
        {rejected.map((source) => (
          <li key={`${source.source}-rejected`}>
            {source.rejected_last_day} {SOURCE_LABELS[source.source] ?? source.source} records in the last day could
            not be read, so totals may be slightly low.
          </li>
        ))}
        <li>
          <Link href="/health" className="link">
            See data health
          </Link>
        </li>
      </ul>
    </div>
  );
}
