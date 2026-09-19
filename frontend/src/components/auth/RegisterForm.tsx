"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { ApiError, api } from "@/lib/api";
import DigilockerAuth from "./DigilockerAuth";
import { landingPathFor } from "./LoginForm";
import dynamic from "next/dynamic";

const GoogleAuth = dynamic(() => import("./GoogleAuth"), { ssr: false });

/**
 * Public registration.
 *
 * Only vendor and consumer are offered. The backend rejects reviewer/admin
 * self-registration (see endpoints/auth.py) because those roles grant access
 * to other people's data -- the options simply are not presented here.
 */
export default function RegisterForm() {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"vendor" | "consumer">("vendor");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const router = useRouter();

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      await api.register({
        email,
        password,
        full_name: fullName || undefined,
        role,
      });
      // Registration does not return a token, so send them to sign in.
      router.push("/login");
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Something went wrong. Please try again."
      );
      setSubmitting(false);
    }
  };

  const handleOAuthSuccess = async () => {
    try {
      const user = await api.me();
      router.replace(landingPathFor(user));
    } catch {
      setError("Failed to load user profile after registration.");
    }
  };

  const inputClass =
    "block w-full rounded-md border-0 py-2 text-text-primary shadow-sm ring-1 ring-inset ring-border-default/20 placeholder:text-text-primary/40 focus:ring-2 focus:ring-inset focus:ring-surface-dark sm:text-sm sm:leading-6 px-3 bg-white";
  const labelClass = "block text-sm font-medium leading-6 text-text-primary";

  return (
    <div className="flex min-h-screen flex-col justify-center px-6 py-12 lg:px-8 bg-brand-bg">
      <div className="sm:mx-auto sm:w-full sm:max-w-sm">
        <h1 className="mt-10 text-center text-2xl font-bold leading-9 tracking-tight text-text-primary font-display">
          Create an account
        </h1>
      </div>

      <div className="mt-10 sm:mx-auto sm:w-full sm:max-w-sm">
        <form className="space-y-6" onSubmit={handleRegister}>
          {error && (
            <p
              role="alert"
              className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 ring-1 ring-inset ring-red-200"
            >
              {error}
            </p>
          )}

          <div>
            <label htmlFor="fullName" className={labelClass}>
              Full Name
            </label>
            <div className="mt-2">
              <input
                id="fullName"
                name="fullName"
                type="text"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                className={inputClass}
              />
            </div>
          </div>

          <div>
            <label htmlFor="email" className={labelClass}>
              Email address
            </label>
            <div className="mt-2">
              <input
                id="email"
                name="email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className={inputClass}
              />
            </div>
          </div>

          <div>
            <label htmlFor="password" className={labelClass}>
              Password
            </label>
            <div className="mt-2">
              <input
                id="password"
                name="password"
                type="password"
                autoComplete="new-password"
                required
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className={inputClass}
              />
            </div>
          </div>

          <fieldset>
            <legend className={labelClass}>I am a</legend>
            <div className="mt-2 grid grid-cols-2 gap-3">
              {(
                [
                  { value: "vendor", label: "Food vendor", hint: "I run a stall" },
                  { value: "consumer", label: "Consumer", hint: "I buy food" },
                ] as const
              ).map((option) => (
                <label
                  key={option.value}
                  className={`cursor-pointer rounded-lg border px-3 py-3 text-center text-sm transition-colors ${
                    role === option.value
                      ? "border-surface-dark bg-surface-dark/5 text-surface-dark ring-1 ring-surface-dark"
                      : "border-border-default/20 bg-white text-text-primary hover:bg-surface-soft"
                  }`}
                >
                  <input
                    type="radio"
                    name="role"
                    value={option.value}
                    checked={role === option.value}
                    onChange={() => setRole(option.value)}
                    className="sr-only"
                  />
                  <span className="block font-semibold">{option.label}</span>
                  <span className="mt-0.5 block text-xs text-text-primary/60">
                    {option.hint}
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          <div>
            <button
              type="submit"
              disabled={submitting}
              className="flex w-full justify-center rounded-full bg-surface-dark px-3 py-3 text-sm font-semibold leading-6 text-text-inverse shadow-sm hover:bg-surface-dark/90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-surface-dark disabled:opacity-60 transition-colors"
            >
              {submitting ? "Creating account…" : "Register"}
            </button>
          </div>
        </form>

        <div className="mt-8">
          <div className="relative">
            <div className="absolute inset-0 flex items-center" aria-hidden="true">
              <div className="w-full border-t border-border-default/10" />
            </div>
            <div className="relative flex justify-center text-sm font-medium leading-6">
              <span className="bg-brand-bg px-6 text-text-primary">Or register with</span>
            </div>
          </div>

          <div className="mt-6 flex flex-col gap-4">
            <GoogleAuth onSuccess={handleOAuthSuccess} onError={setError} />
            <DigilockerAuth onSuccess={handleOAuthSuccess} onError={setError} />
          </div>
        </div>

        <p className="mt-10 text-center text-sm text-text-primary">
          Already have an account?{" "}
          <Link
            href="/login"
            className="font-semibold leading-6 text-surface-dark hover:text-surface-dark/80"
          >
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
