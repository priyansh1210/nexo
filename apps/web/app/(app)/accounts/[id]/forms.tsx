"use client";

import { useActionState } from "react";

import { addNote, addTask, type FormState } from "./actions";

export function NoteForm({ accountId }: { accountId: string }) {
  const [state, action, pending] = useActionState<FormState, FormData>(addNote.bind(null, accountId), {});
  return (
    <form key={state.saved} action={action} className="space-y-2">
      <label htmlFor="note-body" className="sr-only">
        New note
      </label>
      <textarea
        id="note-body"
        name="body"
        rows={3}
        maxLength={5000}
        placeholder="Add a note for the team"
        className="field leading-relaxed"
        aria-describedby={state.error ? "note-error" : undefined}
      />
      {state.error && (
        <p id="note-error" role="alert" className="text-sm text-failed">
          {state.error}
        </p>
      )}
      <button type="submit" className="button" disabled={pending}>
        {pending ? "Adding…" : "Add note"}
      </button>
    </form>
  );
}

export function TaskForm({ accountId, defaultAssignee }: { accountId: string; defaultAssignee: string }) {
  const [state, action, pending] = useActionState<FormState, FormData>(addTask.bind(null, accountId), {});
  return (
    <form key={state.saved} action={action} className="space-y-2">
      <div>
        <label htmlFor="task-title" className="block text-[13px] font-medium">
          New task
        </label>
        <input id="task-title" name="title" maxLength={200} className="field mt-1" placeholder="What needs doing" />
      </div>
      <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-2">
        <div>
          <label htmlFor="task-assignee" className="block text-[13px] text-ink-2">
            Assignee email
          </label>
          <input
            id="task-assignee"
            name="assignee_email"
            type="email"
            defaultValue={defaultAssignee}
            className="field mt-1"
          />
        </div>
        <div>
          <label htmlFor="task-due" className="block text-[13px] text-ink-2">
            Due
          </label>
          <input id="task-due" name="due_on" type="date" className="field mt-1" />
        </div>
      </div>
      {state.error && (
        <p role="alert" className="text-sm text-failed">
          {state.error}
        </p>
      )}
      <button type="submit" className="button" disabled={pending}>
        {pending ? "Adding…" : "Add task"}
      </button>
    </form>
  );
}
