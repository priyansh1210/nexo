// Server-side only: the browser never talks to the API. Pages and Server Actions call it here,
// forwarding the user's session, so the API can stay on the stack's private network.
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { SESSION_COOKIE } from "./session";

export const API_URL = process.env.API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

/** The API's error detail as one readable sentence: it may be text, a list, or an object. */
export function detailText(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => (typeof item === "object" && item && "msg" in item ? String(item.msg) : String(item)))
      .join("; ");
  }
  if (detail && typeof detail === "object") {
    const { message, problems } = detail as { message?: string; problems?: string[] };
    return [message, ...(problems ?? [])].filter(Boolean).join(" ");
  }
  return "Something went wrong.";
}

/** Call the API as the signed-in user. A missing or expired session goes to the sign-in page. */
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) redirect("/login");
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: {
        Cookie: `${SESSION_COOKIE}=${token}`,
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...init.headers,
      },
    });
  } catch {
    // The API is restarting or down: an answer the screen can show, not a crash.
    throw new ApiError(503, "Nexo's API cannot be reached. Try again in a moment.");
  }
  if (response.status === 401) redirect("/login");
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(response.status, detailText(body.detail));
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}
