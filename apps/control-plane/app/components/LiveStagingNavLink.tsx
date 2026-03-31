"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

const LS_THREAD = "kmbl_autonomous_thread_id";

/**
 * Nav target: open live working staging when a session thread exists, else Autonomous (where runs start).
 */
export function LiveStagingNavLink() {
  const [href, setHref] = useState("/autonomous");

  useEffect(() => {
    try {
      const tid = localStorage.getItem(LS_THREAD)?.trim();
      if (tid) {
        setHref(`/habitat/live/${encodeURIComponent(tid)}`);
      }
    } catch {
      /* ignore */
    }
  }, []);

  return (
    <Link href={href} title="Open live working staging preview (requires a session thread from Autonomous)">
      Live staging
    </Link>
  );
}
