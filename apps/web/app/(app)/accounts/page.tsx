import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { DataStatus } from "@/components/data-status";
import { api } from "@/lib/api";
import { daysUntil, formatChange, formatDate, formatMoney, USAGE_STATUS_TEXT } from "@/lib/format";
import type { Account, AccountList, User } from "@/lib/types";

export const metadata: Metadata = { title: "Accounts" };

const SORTS = {
  renewal: { label: "Renews", key: (a: Account) => a.renewal_date },
  name: { label: "Account", key: (a: Account) => a.name.toLowerCase() },
  arr: { label: "ARR", key: (a: Account) => a.arr_usd },
  usage: { label: "Usage, 30 days", key: (a: Account) => a.usage_change ?? Number.POSITIVE_INFINITY },
  tickets: { label: "Open tickets", key: (a: Account) => a.open_tickets },
} as const;
type Sort = keyof typeof SORTS;
const VIEWS = { all: "All", risk: "At risk", mine: "Mine" } as const;
type View = keyof typeof VIEWS;

export default function AccountsPage({ searchParams }: PageProps<"/accounts">) {
  return (
    <>
      <h1 className="text-[22px] font-semibold">Accounts</h1>
      <Suspense fallback={<p className="mt-6 text-sm text-ink-2">Loading accounts…</p>}>
        <Accounts searchParams={searchParams} />
      </Suspense>
    </>
  );
}

async function Accounts({ searchParams }: Pick<PageProps<"/accounts">, "searchParams">) {
  const params = await searchParams;
  const sort: Sort = typeof params.sort === "string" && params.sort in SORTS ? (params.sort as Sort) : "renewal";
  const descending = params.dir === "desc";
  const view: View = typeof params.view === "string" && params.view in VIEWS ? (params.view as View) : "all";
  const [{ accounts, freshness, checks }, me] = await Promise.all([
    api<AccountList>("/accounts"),
    api<User>("/auth/me"),
  ]);
  const usageStale = freshness.some((s) => s.source === "product_events" && s.status !== "fresh");

  const shown = accounts
    .filter((a) => view === "all" || (view === "risk" ? a.is_at_risk : a.owner_email === me.email))
    .sort((a, b) => {
      const [x, y] = [SORTS[sort].key(a), SORTS[sort].key(b)];
      return (x < y ? -1 : x > y ? 1 : 0) * (descending ? -1 : 1);
    });
  const href = (next: Partial<{ sort: Sort; dir: string; view: View }>) => {
    const query = new URLSearchParams({ sort, dir: descending ? "desc" : "asc", view, ...next });
    return `/accounts?${query}`;
  };

  return (
    <div className="mt-4 space-y-5">
      <DataStatus freshness={freshness} checks={checks} />
      <nav aria-label="Show" className="flex gap-4 text-sm">
        {(Object.keys(VIEWS) as View[]).map((key) => (
          <Link
            key={key}
            href={href({ view: key })}
            aria-current={key === view ? "page" : undefined}
            className={key === view ? "font-semibold" : "link"}
          >
            {VIEWS[key]}
            <span className="ml-1 font-normal tabular-nums text-ink-2">
              {key === "all" ? accounts.length : accounts.filter((a) => (key === "risk" ? a.is_at_risk : a.owner_email === me.email)).length}
            </span>
          </Link>
        ))}
      </nav>

      {shown.length === 0 ? (
        <p className="text-sm text-ink-2">
          {view === "mine" ? "You own no accounts." : view === "risk" ? "No account is at risk right now." : "No accounts yet: the pipeline has not loaded the CRM."}
        </p>
      ) : (
        <>
          <ul className="divide-y divide-rule border-y border-rule md:hidden" aria-label="Accounts">
            {shown.map((account) => (
              <AccountItem key={account.account_id} account={account} usageStale={usageStale} />
            ))}
          </ul>
        <div className="hidden overflow-x-auto md:block">
          <table className="table min-w-[860px]">
            <thead>
              <tr>
                <SortHeader column="name" sort={sort} descending={descending} href={href} />
                <th scope="col">Owner</th>
                <SortHeader column="renewal" sort={sort} descending={descending} href={href} />
                <th scope="col">Health</th>
                <SortHeader column="usage" sort={sort} descending={descending} href={href} numeric stale={usageStale} />
                <SortHeader column="tickets" sort={sort} descending={descending} href={href} numeric />
                <SortHeader column="arr" sort={sort} descending={descending} href={href} numeric />
              </tr>
            </thead>
            <tbody>
              {shown.map((account) => (
                <AccountRow key={account.account_id} account={account} usageStale={usageStale} />
              ))}
            </tbody>
          </table>
        </div>
        </>
      )}
    </div>
  );
}

function SortHeader({
  column,
  sort,
  descending,
  href,
  numeric,
  stale,
}: {
  column: Sort;
  sort: Sort;
  descending: boolean;
  href: (next: { sort: Sort; dir: string }) => string;
  numeric?: boolean;
  stale?: boolean;
}) {
  const active = column === sort;
  const nextDir = active && !descending ? "desc" : "asc";
  return (
    <th scope="col" className={numeric ? "num" : undefined} aria-sort={active ? (descending ? "descending" : "ascending") : undefined}>
      <Link href={href({ sort: column, dir: nextDir })} className={active ? "text-ink" : "hover:text-ink"}>
        {SORTS[column].label}
        {active && <span aria-hidden="true">{descending ? " ↓" : " ↑"}</span>}
      </Link>
      {stale && <span className="block font-normal normal-case tracking-normal text-stale">stale</span>}
    </th>
  );
}

function riskReasons(account: Account): string {
  return [
    account.risk_usage_drop && "usage dropped",
    account.risk_stale_ticket && "old high-severity ticket",
    account.risk_overdue_invoice && "overdue invoice",
  ]
    .filter(Boolean)
    .join(", ");
}

function usageText(account: Account): string {
  return account.usage_change === null
    ? (USAGE_STATUS_TEXT[account.usage_status] ?? "Unknown")
    : formatChange(account.usage_change);
}

function AccountItem({ account, usageStale }: { account: Account; usageStale: boolean }) {
  const days = daysUntil(account.renewal_date);
  return (
    <li className="space-y-1 py-3 text-sm">
      <p className="flex items-baseline justify-between gap-3">
        <Link href={`/accounts/${account.account_id}`} className="link text-[15px] font-medium">
          {account.name}
        </Link>
        <span className="text-[13px] capitalize text-ink-2">{account.plan}</span>
      </p>
      <p className="tabular-nums">
        Renews {formatDate(account.renewal_date)}
        <span className="text-ink-2">
          {" "}
          · {days >= 0 ? `in ${days} days` : `${-days} days ago`} · {account.owner_name}
        </span>
      </p>
      <p>
        {account.is_at_risk ? (
          <>
            <span className="font-semibold">At risk:</span> {riskReasons(account)}
          </>
        ) : (
          <span className="text-ink-2">No risk signals</span>
        )}
      </p>
      <p className="text-ink-2 tabular-nums">
        Usage {usageText(account)}
        {usageStale && <span className="text-stale"> (stale)</span>} · {account.open_tickets} open tickets ·{" "}
        {formatMoney(account.arr_usd)}
      </p>
    </li>
  );
}

function AccountRow({ account, usageStale }: { account: Account; usageStale: boolean }) {
  const days = daysUntil(account.renewal_date);
  return (
    <tr>
      <td>
        <Link href={`/accounts/${account.account_id}`} className="link font-medium">
          {account.name}
        </Link>
        <span className="block text-[13px] capitalize text-ink-2">{account.plan}</span>
      </td>
      <td>{account.owner_name}</td>
      <td className="whitespace-nowrap">
        {formatDate(account.renewal_date)}
        <span className="block text-[13px] text-ink-2">{days >= 0 ? `in ${days} days` : `${-days} days ago`}</span>
      </td>
      <td>
        {account.is_at_risk ? (
          <>
            <span className="font-semibold">At risk</span>
            <span className="block text-[13px] text-ink-2">{riskReasons(account)}</span>
          </>
        ) : (
          <span className="text-ink-2">No risk signals</span>
        )}
      </td>
      <td className={`num whitespace-nowrap ${usageStale ? "text-ink-2" : ""}`}>
        {account.usage_change === null ? (
          <span className="text-[13px] text-ink-2">{usageText(account)}</span>
        ) : (
          usageText(account)
        )}
      </td>
      <td className="num">{account.open_tickets}</td>
      <td className="num">{formatMoney(account.arr_usd)}</td>
    </tr>
  );
}
