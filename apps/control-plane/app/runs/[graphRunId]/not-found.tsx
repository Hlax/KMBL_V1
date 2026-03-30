import Link from "next/link";

export default function GraphRunNotFound() {
  return (
    <div className="pub-not-found">
      <h1 className="pub-page-title">Run not found</h1>
      <div className="pub-empty">
        <p className="pub-empty__title">No graph run for this id</p>
        <p className="pub-empty__body">
          The URL does not match a persisted run, or the run was removed from the index. Check the id
          or return to the runs list.
        </p>
        <p style={{ marginTop: "1.25rem" }}>
          <Link href="/runs">← All runs</Link>
        </p>
      </div>
    </div>
  );
}
