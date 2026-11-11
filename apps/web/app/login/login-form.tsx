"use client";

import { useActionState, useEffect, useRef } from "react";

import { signIn, type SignInState } from "./actions";

export function LoginForm() {
  const [state, action, pending] = useActionState<SignInState, FormData>(signIn, {});
  const next = useRef<HTMLInputElement>(null);
  useEffect(() => {
    // Where to go after signing in: the page the proxy sent the person away from.
    if (next.current) next.current.value = new URLSearchParams(window.location.search).get("next") ?? "";
  }, []);

  return (
    <form action={action} className="space-y-4" noValidate>
      <input ref={next} type="hidden" name="next" defaultValue="" />
      <div className="space-y-1.5">
        <label htmlFor="email" className="block text-sm font-medium">
          Email
        </label>
        <input
          id="email"
          name="email"
          type="email"
          autoComplete="username"
          required
          defaultValue={state.email}
          className="field"
          aria-describedby={state.error ? "sign-in-error" : undefined}
        />
      </div>
      <div className="space-y-1.5">
        <label htmlFor="password" className="block text-sm font-medium">
          Password
        </label>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          className="field"
          aria-describedby={state.error ? "sign-in-error" : undefined}
        />
      </div>
      {state.error && (
        <p id="sign-in-error" role="alert" className="text-sm text-failed">
          {state.error}
        </p>
      )}
      <button type="submit" className="button button-primary w-full justify-center" disabled={pending}>
        {pending ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}
