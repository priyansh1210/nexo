"use client";

import { useState, useTransition } from "react";

import { setTaskStatus } from "@/app/(app)/tasks/actions";

/** Done / reopen for one task. The new state shows once the API has saved it. */
export function TaskToggle({ taskId, status, title }: { taskId: number; status: "open" | "done"; title: string }) {
  const [error, setError] = useState<string>();
  const [pending, start] = useTransition();
  const next = status === "open" ? "done" : "open";
  return (
    <span className="inline-flex flex-col items-start">
      <button
        type="button"
        className="link whitespace-nowrap text-[13px]"
        disabled={pending}
        aria-label={`${next === "done" ? "Mark done" : "Reopen"}: ${title}`}
        onClick={() =>
          start(async () => {
            setError(await setTaskStatus(taskId, next));
          })
        }
      >
        {pending ? "Saving…" : next === "done" ? "Mark done" : "Reopen"}
      </button>
      {error && (
        <span role="alert" className="text-[12px] text-failed">
          {error}
        </span>
      )}
    </span>
  );
}
