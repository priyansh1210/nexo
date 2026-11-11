"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { API_URL, detailText } from "@/lib/api";
import { SESSION_COOKIE } from "@/lib/session";

export type SignInState = { error?: string; email?: string };

/** Only a path on this site. "//evil.example", "/\\evil.example" or a full URL would leave it. */
function safeNext(next: FormDataEntryValue | null): string {
  const here = "http://nexo.local";
  const url = new URL(typeof next === "string" && next ? next : "/chat", here);
  return url.origin === here && url.pathname !== "/login" ? url.pathname + url.search : "/chat";
}

export async function signIn(_: SignInState, form: FormData): Promise<SignInState> {
  const email = String(form.get("email") ?? "").trim();
  const password = String(form.get("password") ?? "");
  if (!email || !password) return { error: "Enter your email and password.", email };

  let response: Response;
  try {
    response = await fetch(`${API_URL}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
  } catch {
    return { error: "Nexo's API cannot be reached. Try again in a moment.", email };
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const error = response.status === 401 ? "That email and password do not match." : detailText(body.detail);
    return { error, email };
  }

  // The API answers with its session token in a cookie; the web keeps it in its own.
  const token = response.headers
    .getSetCookie()
    .map((cookie) => cookie.split(";")[0])
    .find((pair) => pair.startsWith(`${SESSION_COOKIE}=`))
    ?.slice(SESSION_COOKIE.length + 1);
  if (!token) return { error: "Signing in failed. Try again.", email };

  (await cookies()).set(SESSION_COOKIE, token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NEXO_COOKIE_SECURE === "1", // set to 1 when served over HTTPS
    maxAge: 7 * 86_400,
    path: "/",
  });
  redirect(safeNext(form.get("next")));
}
