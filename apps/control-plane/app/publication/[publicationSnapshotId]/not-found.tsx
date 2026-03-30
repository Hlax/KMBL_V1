import Link from "next/link";

export default function PublicationNotFound() {
  return (
    <div className="pub-not-found">
      <h1 className="pub-page-title">Publication not found</h1>
      <div className="pub-empty">
        <p className="pub-empty__title">No canon snapshot for this id</p>
        <p className="pub-empty__body">
          The id in the URL does not match a persisted publication row. Check the link or open the
          publication index to pick a snapshot from the list.
        </p>
        <p style={{ marginTop: "1.25rem" }}>
          <Link href="/publication">← Publication index</Link>
        </p>
      </div>
    </div>
  );
}
