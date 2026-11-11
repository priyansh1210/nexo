"use server";

import { ApiError, api } from "@/lib/api";
import type { Account, AccountList, Answer, Proposal } from "@/lib/types";

export type Asked = { answer: Answer; accounts: Account[] } | { error: string };

/** Ask the assistant. A list answer also brings the listed accounts, for the inline table. */
export async function ask(conversationId: string, message: string): Promise<Asked> {
  try {
    const answer = await api<Answer>(`/conversations/${encodeURIComponent(conversationId)}/messages`, {
      method: "POST",
      body: JSON.stringify({ message }),
    });
    const listed = answer.tool_calls
      .filter((call) => call.name === "list_renewals")
      .flatMap((call) => answer.evidence[call.id]?.records ?? []);
    if (!listed.length) return { answer, accounts: [] };
    const { accounts } = await api<AccountList>("/accounts");
    return { answer, accounts: listed.flatMap((id) => accounts.filter((a) => a.account_id === id)) };
  } catch (error) {
    if (error instanceof ApiError) return { error: error.message };
    throw error; // a redirect to sign-in, or a bug
  }
}

export type Decided = { proposal: Proposal } | { error: string };

export async function decide(
  proposalId: number,
  decision: "approve" | "edit" | "reject",
  params: Record<string, string | null> = {},
): Promise<Decided> {
  try {
    const proposal = await api<Proposal>(`/actions/${proposalId}/decision`, {
      method: "POST",
      body: JSON.stringify({ decision, params }),
    });
    return { proposal };
  } catch (error) {
    if (error instanceof ApiError) return { error: error.message };
    throw error;
  }
}
