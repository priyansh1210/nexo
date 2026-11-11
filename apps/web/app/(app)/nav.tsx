"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const PLACES = [
  { href: "/chat", label: "Chat" },
  { href: "/accounts", label: "Accounts" },
  { href: "/tasks", label: "Tasks" },
  { href: "/audit", label: "Audit" },
  { href: "/health", label: "Data health" },
] as const;

/** The current place's highlight needs the URL, which streams in; until then the links show plainly. */
export function CurrentNav() {
  return <Nav path={usePathname()} />;
}

export function Nav({ path = "" }: { path?: string }) {
  return (
    <nav aria-label="Main" className="-mx-1 flex gap-1 overflow-x-auto">
      {PLACES.map(({ href, label }) => {
        const current = path === href || path.startsWith(`${href}/`);
        return (
          <Link
            key={href}
            href={href}
            aria-current={current ? "page" : undefined}
            className={`whitespace-nowrap rounded-md px-2.5 py-1.5 text-sm ${
              current ? "font-semibold text-ink" : "text-ink-2 hover:text-ink"
            }`}
          >
            {label}
            {current && <span className="mt-0.5 block h-0.5 rounded-full bg-accent" aria-hidden="true" />}
          </Link>
        );
      })}
    </nav>
  );
}
