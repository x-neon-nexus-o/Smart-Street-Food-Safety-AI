"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { clearToken } from "@/lib/auth";
import { CurrentUser } from "@/lib/types";

export default function ConsumerProfile() {
  const router = useRouter();
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadUser() {
      try {
        const userData = await api.me();
        setUser(userData);
      } catch {
        // Not authenticated
      } finally {
        setLoading(false);
      }
    }
    loadUser();
  }, []);

  const handleLogout = () => {
    clearToken();
    router.push("/login");
  };

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50">
        <div className="text-sm text-gray-500">Loading profile...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 px-6 py-10">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Profile</h1>

      <div className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-inset ring-gray-200 space-y-4">
        <div>
          <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1">
            Account Details
          </h2>
          {user ? (
            <div className="space-y-2">
              {user.full_name && (
                <div className="text-sm font-medium text-gray-900">
                  {user.full_name}
                </div>
              )}
              <div className="text-sm text-gray-600">{user.email}</div>
              <div className="text-xs text-gray-500 capitalize pt-1">
                Role: {user.role}
              </div>
            </div>
          ) : (
            <div className="text-sm text-gray-500">Not logged in</div>
          )}
        </div>
      </div>

      <div className="mt-8">
        <button
          onClick={handleLogout}
          className="w-full rounded-xl bg-white px-4 py-3 text-sm font-semibold text-red-600 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50"
        >
          Sign Out
        </button>
      </div>
    </div>
  );
}
