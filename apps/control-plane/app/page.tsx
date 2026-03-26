import Link from "next/link";

export default function HomePage() {
  return (
    <>
      <h1>KMBL</h1>
      <p className="muted">
        Control plane shell. The orchestrator (Python + LangGraph + FastAPI) owns
        execution; KiloClaw hosts planner, generator, and evaluator roles.
      </p>
      <p>
        <Link href="/status">Status placeholder</Link>
      </p>
    </>
  );
}
