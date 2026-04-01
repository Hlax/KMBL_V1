"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { LiveStagingNavLink } from "./LiveStagingNavLink";

function navClass(active: boolean) {
  return active ? "cp-nav__link cp-nav__link--active" : "cp-nav__link";
}

export function ControlPlaneNav() {
  const pathname = usePathname() ?? "";
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  const homeActive = pathname === "/autonomous" || pathname === "/";
  const graphRunsActive = pathname.startsWith("/runs");
  const stagingReviewActive = pathname.startsWith("/review");
  const publicActive = pathname.startsWith("/publication");

  return (
    <header className="cp-header">
      <div className="cp-nav-bar">
        <Link href="/autonomous" className="cp-brand">
          KMBL
        </Link>
        <nav className="cp-nav cp-nav--primary" aria-label="Primary">
          <Link href="/autonomous" className={navClass(homeActive)}>
            Home
          </Link>
          <LiveStagingNavLink />
          <Link href="/runs" className={navClass(graphRunsActive)}>
            Graph runs
          </Link>
          <Link href="/review" className={navClass(stagingReviewActive)}>
            Staging review
          </Link>
          <Link href="/publication" className={navClass(publicActive)}>
            Public
          </Link>
        </nav>
        <div className="cp-nav__overflow-wrap">
          <button
            type="button"
            className="cp-nav__menu-btn"
            aria-expanded={open}
            aria-controls="cp-overflow-menu"
            onClick={() => setOpen((o) => !o)}
          >
            Menu
          </button>
          {open ? (
            <div
              id="cp-overflow-menu"
              className="cp-overflow-panel"
              role="menu"
              aria-label="More"
            >
              <Link
                href="/status"
                className="cp-overflow-panel__link"
                role="menuitem"
                onClick={() => setOpen(false)}
              >
                Status
              </Link>
              <Link
                href="/autonomous"
                className="cp-overflow-panel__link"
                role="menuitem"
                onClick={() => setOpen(false)}
              >
                Launch (Autonomous)
              </Link>
            </div>
          ) : null}
        </div>
      </div>
      <p className="cp-tagline">Autonomous creative operating system</p>
    </header>
  );
}
