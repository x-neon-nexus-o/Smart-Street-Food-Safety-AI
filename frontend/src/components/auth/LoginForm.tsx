"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { ApiError, api } from "@/lib/api";
import { setToken } from "@/lib/auth";
import type { CurrentUser } from "@/lib/types";
import DigilockerAuth from "./DigilockerAuth";
import dynamic from "next/dynamic";

const GoogleAuth = dynamic(() => import("./GoogleAuth"), { ssr: false });

/** Where to send someone after login, based on their role and profile. */
export function landingPathFor(user: CurrentUser): string {
  if (user.role === "reviewer" || user.role === "admin") return "/reviewer";
  if (user.role === "consumer") return "/consumer";
  // A vendor with no vendor_id has not completed stall onboarding yet, so
  // send them to the form rather than to the scan tab.
  return user.vendor_id === null ? "/vendor" : "/vendor/scan";
}

export default function LoginForm({ nextPath }: { nextPath?: string }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const router = useRouter();

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      const token = await api.login(email, password);
      // The cookie must be set before /me is called: the api helper reads the
      // token from it to build the Authorization header.
      setToken(token.access_token);

      const user = await api.me();
      router.replace(nextPath || landingPathFor(user));
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
      router.replace(nextPath || landingPathFor(user));
    } catch {
      setError("Failed to load user profile after login.");
    }
  };

  return (
    <div className="flex min-h-screen flex-col justify-center px-6 py-12 lg:px-8 bg-brand-bg">
      <div className="sm:mx-auto sm:w-full sm:max-w-sm">
        <h1 className="mt-10 text-center text-2xl font-bold leading-9 tracking-tight text-text-primary font-display">
          Sign in to your account
        </h1>
      </div>

      <div className="mt-10 sm:mx-auto sm:w-full sm:max-w-sm">
        <form className="space-y-6" onSubmit={handleLogin}>
          {error && (
            <p
              role="alert"
              className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 ring-1 ring-inset ring-red-200"
            >
              {error}
            </p>
          )}

          <div>
            <label
              htmlFor="email"
              className="block text-sm font-medium leading-6 text-text-primary"
            >
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
                className="block w-full rounded-md border-0 py-2 text-text-primary shadow-sm ring-1 ring-inset ring-border-default/20 placeholder:text-text-primary/40 focus:ring-2 focus:ring-inset focus:ring-surface-dark sm:text-sm sm:leading-6 px-3 bg-white"
              />
            </div>
          </div>

          <div>
            <label
              htmlFor="password"
              className="block text-sm font-medium leading-6 text-text-primary"
            >
              Password
            </label>
            <div className="mt-2">
              <input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="block w-full rounded-md border-0 py-2 text-text-primary shadow-sm ring-1 ring-inset ring-border-default/20 placeholder:text-text-primary/40 focus:ring-2 focus:ring-inset focus:ring-surface-dark sm:text-sm sm:leading-6 px-3 bg-white"
              />
            </div>
          </div>

          <div>
            <button
              type="submit"
              disabled={submitting}
              className="flex w-full justify-center rounded-full bg-surface-dark px-3 py-3 text-sm font-semibold leading-6 text-text-inverse shadow-sm hover:bg-surface-dark/90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-surface-dark disabled:opacity-60 transition-colors"
            >
              {submitting ? "Signing in…" : "Sign in"}
            </button>
          </div>
        </form>

        <div className="mt-8">
          <div className="relative">
            <div className="absolute inset-0 flex items-center" aria-hidden="true">
              <div className="w-full border-t border-border-default/10" />
            </div>
            <div className="relative flex justify-center text-sm font-medium leading-6">
              <span className="bg-brand-bg px-6 text-text-primary">Or continue with</span>
            </div>
          </div>

          <div className="mt-6 flex flex-col gap-4">
            <GoogleAuth onSuccess={handleOAuthSuccess} onError={setError} />
            <DigilockerAuth onSuccess={handleOAuthSuccess} onError={setError} />
          </div>
        </div>

        <p className="mt-10 text-center text-sm text-text-primary">
          Not a member?{" "}
          <Link
            href="/register"
            className="font-semibold leading-6 text-surface-dark hover:text-surface-dark/80"
          >
            Register here
          </Link>
        </p>
      </div>
    </div>
  );
}
