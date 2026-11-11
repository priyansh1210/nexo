"use server";

import { refresh } from "next/cache";

import { ApiError, api } from "@/lib/api";

export type FormState = { error?: string; saved?: number };

async function save(path: string, body: object, state: FormState): Promise<FormState> {
  try {
    await api(path, { method: "POST", body: JSON.stringify(body) });
  } catch (error) {
    if (error instanceof ApiError) return { error: error.message, saved: state.saved };
    throw error;
  }
  refresh();
  return { saved: (state.saved ?? 0) + 1 }; // a new count clears the form
}

export async function addNote(accountId: string, state: FormState, form: FormData): Promise<FormState> {
  const body = String(form.get("body") ?? "").trim();
  if (!body) return { error: "Write the note first.", saved: state.saved };
  return save(`/accounts/${encodeURIComponent(accountId)}/notes`, { body }, state);
}

export async function addTask(accountId: string, state: FormState, form: FormData): Promise<FormState> {
  const title = String(form.get("title") ?? "").trim();
  if (!title) return { error: "Give the task a title.", saved: state.saved };
  const assignee = String(form.get("assignee_email") ?? "").trim();
  const due = String(form.get("due_on") ?? "");
  return save(
    `/accounts/${encodeURIComponent(accountId)}/tasks`,
    { title, assignee_email: assignee || null, due_on: due || null },
    state,
  );
}
