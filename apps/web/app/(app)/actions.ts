"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { api } from "@/lib/api";
import { SESSION_COOKIE } from "@/lib/session";

export async function signOut() {
  await api("/auth/logout", { method: "POST" }).catch(() => undefined); // signed out either way
  (await cookies()).delete(SESSION_COOKIE);
  redirect("/login");
}
