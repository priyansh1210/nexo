import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { TaskToggle } from "@/components/task-toggle";
import { api } from "@/lib/api";
import { daysUntil, formatDate } from "@/lib/format";
import type { AccountList, Task, User } from "@/lib/types";

export const metadata: Metadata = { title: "Tasks" };

export default function TasksPage({ searchParams }: PageProps<"/tasks">) {
  return (
    <>
      <h1 className="text-[22px] font-semibold">Tasks</h1>
      <Suspense fallback={<p className="mt-6 text-sm text-ink-2">Loading tasks…</p>}>
        <Tasks searchParams={searchParams} />
      </Suspense>
    </>
  );
}

async function Tasks({ searchParams }: Pick<PageProps<"/tasks">, "searchParams">) {
  const { view } = await searchParams;
  const team = view === "team";
  const [tasks, me, { accounts }] = await Promise.all([
    api<Task[]>(`/tasks${team ? "" : "?mine=true"}`),
    api<User>("/auth/me"),
    api<AccountList>("/accounts"),
  ]);
  const names = new Map(accounts.map((a) => [a.account_id, a.name]));
  const open = tasks.filter((t) => t.status === "open");
  const done = tasks.filter((t) => t.status === "done");
  const canWrite = me.role !== "viewer";

  return (
    <div className="mt-4 space-y-6">
      <nav aria-label="Whose tasks" className="flex gap-4 text-sm">
        <Link href="/tasks" aria-current={team ? undefined : "page"} className={team ? "link" : "font-semibold"}>
          Assigned to me
        </Link>
        <Link href="/tasks?view=team" aria-current={team ? "page" : undefined} className={team ? "font-semibold" : "link"}>
          Whole team
        </Link>
      </nav>

      {tasks.length === 0 ? (
        <p className="text-sm text-ink-2">
          {team
            ? "No tasks yet. Add one from an account, or ask the assistant to draft one."
            : "Nothing is assigned to you. Tasks the assistant drafts for you appear here once you approve them."}
        </p>
      ) : (
        <>
          <TaskTable tasks={open} names={names} me={me} canWrite={canWrite} team={team} caption={`Open · ${open.length}`} />
          {done.length > 0 && (
            <details>
              <summary className="link cursor-pointer text-sm">Done · {done.length}</summary>
              <div className="mt-3">
                <TaskTable tasks={done} names={names} me={me} canWrite={canWrite} team={team} />
              </div>
            </details>
          )}
        </>
      )}
    </div>
  );
}

function TaskTable({
  tasks,
  names,
  me,
  canWrite,
  team,
  caption,
}: {
  tasks: Task[];
  names: Map<string, string>;
  me: User;
  canWrite: boolean;
  team: boolean;
  caption?: string;
}) {
  if (!tasks.length) return <p className="text-sm text-ink-2">No open tasks.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="table min-w-[720px]">
        {caption && <caption className="label pb-2 text-left">{caption}</caption>}
        <thead>
          <tr>
            <th scope="col">Task</th>
            <th scope="col">Account</th>
            {team && <th scope="col">Assignee</th>}
            <th scope="col">Due</th>
            <th scope="col">From</th>
            {canWrite && (
              <th scope="col">
                <span className="sr-only">Change</span>
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => {
            const overdue = task.status === "open" && task.due_on !== null && daysUntil(task.due_on) < 0;
            const ownChat = task.conversation_id && task.created_by_email === me.email;
            return (
              <tr key={task.task_id} className={task.status === "done" ? "text-ink-2" : undefined}>
                <td>
                  <span className="font-medium">{task.title}</span>
                  {task.detail && <span className="block text-[13px] text-ink-2">{task.detail}</span>}
                </td>
                <td>
                  <Link href={`/accounts/${task.account_id}`} className="link">
                    {names.get(task.account_id) ?? task.account_id}
                  </Link>
                </td>
                {team && <td>{task.assignee_name ?? <span className="text-ink-2">Unassigned</span>}</td>}
                <td className="whitespace-nowrap">
                  {task.due_on ? (
                    <>
                      {formatDate(task.due_on)}
                      {overdue && <span className="block text-[13px] font-semibold">Overdue</span>}
                    </>
                  ) : (
                    <span className="text-ink-2">No date</span>
                  )}
                </td>
                <td className="text-[13px]">
                  {ownChat ? (
                    <Link href={`/chat?c=${task.conversation_id}`} className="link">
                      Your chat
                    </Link>
                  ) : task.conversation_id ? (
                    <span className="text-ink-2">{task.created_by_name}&apos;s chat</span>
                  ) : (
                    <span className="text-ink-2">{task.created_by_name}</span>
                  )}
                </td>
                {canWrite && (
                  <td>
                    <TaskToggle taskId={task.task_id} status={task.status} title={task.title} />
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
