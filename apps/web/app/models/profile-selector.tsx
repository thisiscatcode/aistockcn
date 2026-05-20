"use client";

import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useTransition } from "react";

type ModelProfile = {
  name?: unknown;
  label?: unknown;
};

export function ProfileSelector({
  profiles,
  selectedProfile,
  basePath = "/models",
  label = "Active model"
}: {
  profiles: ModelProfile[];
  selectedProfile: string;
  basePath?: string;
  label?: string;
}) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();

  return (
    <label className="model-profile-selector">
      <span>{label}</span>
      <select
        aria-label="Select active model"
        value={selectedProfile}
        onChange={(event) => {
          const profile = event.target.value;
          startTransition(() => {
            router.push(`${basePath}?profile=${encodeURIComponent(profile)}` as Route);
          });
        }}
      >
        {profiles.map((profile) => {
          const name = String(profile.name ?? "");
          const label = String(profile.label ?? name);
          return (
            <option key={name} value={name}>
              {label} ({name})
            </option>
          );
        })}
      </select>
      {isPending ? <span className="model-profile-selector-pending">Updating...</span> : null}
    </label>
  );
}
