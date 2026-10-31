"use client";

import { useEffect, useState } from "react";

import { API_URL, routes } from "@/api/client";

type Status = "checking" | "up" | "down";

export function ApiStatus() {
  const [status, setStatus] = useState<Status>("checking");

  useEffect(() => {
    const controller = new AbortController();
    // A scale-to-zero backend can take a few seconds to wake up.
    const timeout = setTimeout(() => controller.abort(), 15_000);

    fetch(`${API_URL}${routes.healthz}`, { signal: controller.signal })
      .then((res) => setStatus(res.ok ? "up" : "down"))
      .catch(() => setStatus("down"))
      .finally(() => clearTimeout(timeout));

    return () => {
      clearTimeout(timeout);
      controller.abort();
    };
  }, []);

  const label = {
    checking: "Waking up the server…",
    up: "API is up",
    down: "API is unreachable",
  }[status];

  const dot = {
    checking: "bg-amber-400 animate-pulse",
    up: "bg-emerald-500",
    down: "bg-red-500",
  }[status];

  return (
    <p className="flex items-center gap-2 text-sm text-zinc-600 dark:text-zinc-400" role="status">
      <span className={`inline-block h-2.5 w-2.5 rounded-full ${dot}`} aria-hidden />
      {label}
    </p>
  );
}
