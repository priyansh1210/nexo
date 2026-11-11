import type { Metadata } from "next";

import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Sign in" };

// Fully static: the form is in the first HTML, so nothing replaces it while someone is typing.
export default function LoginPage() {
  return (
    <main className="mx-auto flex min-h-dvh max-w-sm flex-col justify-center px-6 py-16">
      <p className="text-lg font-semibold tracking-tight">Nexo</p>
      <h1 className="mt-6 text-[22px] font-semibold">Sign in</h1>
      <p className="mt-1 text-sm text-ink-2">
        Every answer here cites the data it came from and says how fresh that data is.
      </p>
      <div className="mt-8">
        <LoginForm />
      </div>
      <p className="mt-8 text-[13px] text-ink-2">Running the demo? The sign-ins are listed in the README.</p>
    </main>
  );
}
