"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import Image from "next/image";
import { useAuth } from "@/components/AuthProvider";
import { useProjectStore } from "@/hooks/useProjectStore";

interface Starter {
  id: string;
  name: string;
  blurb: string;
}

const STARTERS: Starter[] = [
  {
    id: "enclosure",
    name: "An enclosure",
    blurb: "A case with walls, mounting holes and a lid for a board.",
  },
  {
    id: "robot",
    name: "A small robot",
    blurb: "Chassis plate, motors, wheels and a controller.",
  },
  {
    id: "bracket",
    name: "A bracket",
    blurb: "One part, from a sentence, tuned by numbers.",
  },
];

/** First run for a new account: name the project, then walk into the bench. */
export default function OnboardingPage() {
  const router = useRouter();
  const { status } = useAuth();
  const store = useProjectStore();
  const [step, setStep] = useState<0 | 1>(0);
  const [name, setName] = useState("");
  const [starter, setStarter] = useState<string>(STARTERS[0]!.id);

  useEffect(() => {
    if (status === "signed-out") router.replace("/signin?next=/onboarding");
  }, [status, router]);

  const start = async () => {
    const label = name.trim() || STARTERS.find((s) => s.id === starter)?.name || "My project";
    await store.startProject(label);
    router.push("/workspace");
  };

  return (
    <div className="onboard">
      <header className="onboard-bar">
        <Image
          src="/logo-removebg.png"
          alt="cgen"
          width={36}
          height={36}
          className="brand-logo"
          priority
        />
        <span className="mono">Set up the bench</span>
        <span className="topbar-spacer" />
        <Link className="onboard-skip mono" href="/workspace">
          Skip for now
        </Link>
      </header>

      <ol className="onboard-steps" aria-label="Progress">
        <li className={step === 0 ? "onboard-step is-current" : "onboard-step is-done"}>
          <span className="mono">01</span> Name it
        </li>
        <li className={step === 1 ? "onboard-step is-current" : "onboard-step"}>
          <span className="mono">02</span> First part
        </li>
      </ol>

      {step === 0 ? (
        <section className="onboard-card">
          <h1 className="onboard-title">What are you working on?</h1>
          <p className="onboard-sub">
            One name for this project. You can add more workspaces later.
          </p>
          <label className="onboard-field">
            <span className="mono">Project name</span>
            <input
              className="object-input onboard-input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Robot chassis"
              autoFocus
            />
          </label>
          <button
            type="button"
            className="generate-button onboard-next"
            onClick={() => setStep(1)}
          >
            Continue
          </button>
        </section>
      ) : (
        <section className="onboard-card">
          <h1 className="onboard-title">Pick a starting point</h1>
          <p className="onboard-sub">
            Just a shortcut. You can describe anything in the workspace.
          </p>
          <ul className="onboard-options">
            {STARTERS.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  className={
                    item.id === starter
                      ? "onboard-option is-selected"
                      : "onboard-option"
                  }
                  onClick={() => setStarter(item.id)}
                  aria-pressed={item.id === starter}
                >
                  <span className="onboard-option-name">{item.name}</span>
                  <span className="onboard-option-blurb">{item.blurb}</span>
                </button>
              </li>
            ))}
          </ul>
          <div className="onboard-actions">
            <button
              type="button"
              className="onboard-back mono"
              onClick={() => setStep(0)}
            >
              Back
            </button>
            <button
              type="button"
              className="generate-button onboard-next"
              onClick={() => void start()}
            >
              Open the bench
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
