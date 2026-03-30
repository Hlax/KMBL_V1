import Link from "next/link";

/**
 * Visible operator pipeline: Run → Review → Preview → Publish.
 * No new routes — links to existing surfaces.
 */
export function OperatorFlowStrip() {
  return (
    <div className="op-flow-strip" role="navigation" aria-label="Operator pipeline">
      <span className="op-flow-strip__title">Flow</span>
      <ol className="op-flow-strip__steps">
        <li>
          <Link href="/runs">Run</Link>
          <span className="op-flow-strip__hint">graph_run</span>
        </li>
        <li aria-hidden className="op-flow-strip__arrow">
          →
        </li>
        <li>
          <Link href="/review">Review</Link>
          <span className="op-flow-strip__hint">staging_snapshot</span>
        </li>
        <li aria-hidden className="op-flow-strip__arrow">
          →
        </li>
        <li>
          <span className="op-flow-strip__preview">Preview</span>
          <span className="op-flow-strip__hint">static preview &amp; artifacts on staging</span>
        </li>
        <li aria-hidden className="op-flow-strip__arrow">
          →
        </li>
        <li>
          <Link href="/publication">Publish</Link>
          <span className="op-flow-strip__hint">publication_snapshot</span>
        </li>
      </ol>
    </div>
  );
}
