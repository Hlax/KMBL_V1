import Link from "next/link";

export default function StagingReviewNotFound() {
  return (
    <div className="pub-not-found">
      <h1 className="pub-page-title">Staging snapshot not found</h1>
      <div className="pub-empty">
        <p className="pub-empty__title">No staging row for this id</p>
        <p className="pub-empty__body">
          The id in the URL does not match a persisted staging snapshot. Return to the review list
          or pick a snapshot from a recent run or proposal card.
        </p>
        <p style={{ marginTop: "1.25rem" }}>
          <Link href="/review">← Review list</Link>
        </p>
      </div>
    </div>
  );
}
