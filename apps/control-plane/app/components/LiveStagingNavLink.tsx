"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

const LS_THREAD = "kmbl_autonomous_thread_id";

type Props = {
  /** Merged with active state for primary nav styling */
  className?: string;
};

/**
 * Nav target: open live habitat when a session thread exists, else Autonomous (where runs start).
 */
export function LiveStagingNavLink({ className = "" }: Props) {
  const pathname = usePathname() ?? "";
  const [href, setHref] = useState("/autonomous");

  const syncHref = useCallback(() => {
    try {
      const tid = localStorage.getItem(LS_THREAD)?.trim();
      setHref(tid ? `/habitat/live/${encodeURIComponent(tid)}` : "/autonomous");
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    syncHref();
    window.addEventListener("storage", syncHref);
    window.addEventListener("focus", syncHref);
    return () => {
      window.removeEventListener("storage", syncHref);
      window.removeEventListener("focus", syncHref);
    };
  }, [syncHref, pathname]);

  const active = pathname.startsWith("/habitat/live");
  const merged =
    `${className} cp-nav__link ${active ? "cp-nav__link--active" : ""}`.trim();

  return (
    <Link
      href={href}
      className={merged}
      title="Open live habitat (mutable working staging; set a session thread from Home)"
    >
      Live Habitat
    </Link>
  );
}
