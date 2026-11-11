import Link from "next/link";
import { Suspense } from "react";

import { api } from "@/lib/api";
import type { User } from "@/lib/types";

import { signOut } from "./actions";
import { CurrentNav, Nav } from "./nav";

export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <>
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-3 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <header className="border-b border-rule">
        <div className="mx-auto flex max-w-[1280px] flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 sm:px-6">
          <Link href="/chat" className="text-lg font-semibold tracking-tight">
            Nexo
          </Link>
          <div className="order-3 w-full sm:order-none sm:w-auto sm:flex-1">
            <Suspense fallback={<Nav />}>
              <CurrentNav />
            </Suspense>
          </div>
          <Suspense fallback={<span className="ml-auto text-sm text-ink-2 sm:ml-0">…</span>}>
            <Account />
          </Suspense>
        </div>
      </header>
      <main id="main" className="mx-auto max-w-[1280px] px-4 pb-16 pt-6 sm:px-6">
        {children}
      </main>
    </>
  );
}

async function Account() {
  const user = await api<User>("/auth/me");
  return (
    <form action={signOut} className="ml-auto flex items-center gap-3 text-sm sm:ml-0">
      <span>
        <span className="font-medium">{user.name}</span>
        <span className="text-ink-2"> · {user.role === "csm" ? "CSM" : user.role}</span>
      </span>
      <button type="submit" className="link">
        Sign out
      </button>
    </form>
  );
}
