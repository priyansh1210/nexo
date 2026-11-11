"use server";

import { refresh } from "next/cache";

import { ApiError, api } from "@/lib/api";

/** Mark a task done or open again. Returns an error message, or nothing when it worked. */
export async function setTaskStatus(taskId: number, status: "open" | "done"): Promise<string | undefined> {
  try {
    await api(`/tasks/${taskId}`, { method: "PATCH", body: JSON.stringify({ status }) });
  } catch (error) {
    if (error instanceof ApiError) return error.message;
    throw error;
  }
  refresh();
}
