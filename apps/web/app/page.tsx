import { Suspense } from "react";

// Phase 0 placeholder: proves the web container reaches the API. The real UI is designed in Phase 6.
async function ApiStatus() {
  let text = "unreachable";
  try {
    const res = await fetch(`${process.env.API_URL}/health`);
    const body: { db: boolean } = await res.json();
    text = body.db ? "ok, database connected" : "ok, database not connected";
  } catch {
    // keep "unreachable"
  }
  return <p>API: {text}</p>;
}

export default function Home() {
  return (
    <main className="p-8">
      <h1 className="text-xl font-semibold">Nexo</h1>
      <Suspense fallback={<p>API: checking</p>}>
        <ApiStatus />
      </Suspense>
    </main>
  );
}
