import type { Metadata } from "next";
import { connection } from "next/server";
import { Suspense } from "react";

import { api } from "@/lib/api";
import type { HistoryEntry } from "@/lib/types";

import { Chat } from "./chat";

export const metadata: Metadata = { title: "Chat" };

const CONVERSATION = /^[A-Za-z0-9_-]{1,64}$/;

export default function ChatPage({ searchParams }: PageProps<"/chat">) {
  return (
    <Suspense fallback={<p className="text-sm text-ink-2">Opening the conversation…</p>}>
      <Conversation searchParams={searchParams} />
    </Suspense>
  );
}

async function Conversation({ searchParams }: Pick<PageProps<"/chat">, "searchParams">) {
  const { c, ask } = await searchParams;
  const id = typeof c === "string" && CONVERSATION.test(c) ? c : undefined;
  const history = id ? await api<HistoryEntry[]>(`/conversations/${id}`) : [];
  // A new conversation gets its id now, per request; it reaches the address once the first
  // question is sent.
  if (!id) await connection();
  const conversationId = id ?? crypto.randomUUID().slice(0, 13);
  return (
    <Chat
      key={conversationId}
      conversationId={conversationId}
      isNew={!id}
      history={history}
      prefill={typeof ask === "string" ? ask.slice(0, 2000) : ""}
    />
  );
}
