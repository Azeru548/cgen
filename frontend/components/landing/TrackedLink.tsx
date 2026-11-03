"use client";

import Link from "next/link";
import { useEffect } from "react";
import { track, type TelemetryEvent } from "@/lib/telemetry";

/** A nav link that records one aggregate event. The landing page is a server
 *  component, so only the clicky bits need to be client. */
export function TrackedLink({
  href,
  className,
  event,
  children,
}: {
  href: string;
  className?: string;
  event: TelemetryEvent;
  children: React.ReactNode;
}) {
  return (
    <Link href={href} className={className} onClick={() => track(event)}>
      {children}
    </Link>
  );
}

/** One landing view per page load, so launch traffic has a denominator. */
export function LandingPing() {
  useEffect(() => {
    track("landing_view");
  }, []);
  return null;
}
