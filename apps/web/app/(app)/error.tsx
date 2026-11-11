"use client";

import { Icon } from "@/components/icons";

export default function ScreenError({ retry }: { error: Error & { digest?: string }; retry: () => void }) {
  return (
    <div role="alert" className="max-w-xl space-y-3">
      <p className="flex items-center gap-2 font-semibold">
        <Icon name="warning" className="size-5 text-failed" />
        This screen could not load.
      </p>
      <p className="text-sm text-ink-2">
        Nexo&apos;s API may be restarting, or the warehouse may still be building. Nothing you entered was lost.
      </p>
      <button type="button" className="button" onClick={() => retry()}>
        Try again
      </button>
    </div>
  );
}
