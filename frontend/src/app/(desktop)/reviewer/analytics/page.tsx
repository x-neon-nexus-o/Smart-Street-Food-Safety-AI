"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { reviewerApi } from "@/lib/reviewerApi";
import { ApiError } from "@/lib/api";

type AnalyticsRow = {
  date: string;
  checks_performed: number;
  scans_performed: number;
  flags_created: number;
  average_score?: number | null;
  total_stalls?: number;
  assessed_stalls?: number;
  flagged_stalls?: number;
};

export default function AnalyticsPage() {
  const router = useRouter();
  const [data, setData] = useState<AnalyticsRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await reviewerApi.analytics(30);
      setData((response.items as AnalyticsRow[]) || []);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.push("/login?next=/reviewer/analytics");
        return;
      }
      setError(err instanceof ApiError ? err.message : "Failed to load analytics");
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="max-w-7xl">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-gray-900">Analytics Dashboard</h1>
        <p className="mt-1 text-sm text-gray-600">
          Trends and activity metrics across the platform (last 30 days).
        </p>
      </div>

      {error && (
        <div className="rounded-md bg-red-50 p-4 mb-6">
          <h3 className="text-sm font-medium text-red-800">Error loading data</h3>
          <div className="mt-2 text-sm text-red-700">{error}</div>
        </div>
      )}

      {loading ? (
        <p className="text-sm text-gray-500">Loading metrics…</p>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Trend chart placeholder since we don't have a chart library like Recharts installed */}
          <div className="rounded-lg bg-white p-6 ring-1 ring-inset ring-gray-200">
            <h2 className="text-base font-semibold text-gray-900 mb-4">Activity Timeline</h2>
            
            {data.length === 0 ? (
              <div className="h-64 flex items-center justify-center bg-gray-50 rounded border border-dashed border-gray-300">
                <span className="text-sm text-gray-500">No activity data available</span>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200 text-sm text-left">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-4 py-2 font-medium text-gray-500">Date</th>
                      <th className="px-4 py-2 font-medium text-gray-500 text-right">Checks</th>
                      <th className="px-4 py-2 font-medium text-gray-500 text-right">Scans</th>
                      <th className="px-4 py-2 font-medium text-gray-500 text-right">Flags</th>
                      <th className="px-4 py-2 font-medium text-gray-500 text-right">Avg Score</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {data.map((row, i) => (
                      <tr key={i} className="hover:bg-gray-50">
                        <td className="px-4 py-2 whitespace-nowrap text-gray-900">
                          {new Date(row.date).toLocaleDateString()}
                        </td>
                        <td className="px-4 py-2 text-right text-gray-600">{row.checks_performed}</td>
                        <td className="px-4 py-2 text-right text-gray-600">{row.scans_performed}</td>
                        <td className="px-4 py-2 text-right text-gray-600">{row.flags_created}</td>
                        <td className="px-4 py-2 text-right text-gray-600">
                          {row.average_score ? row.average_score.toFixed(1) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
          
          <div className="space-y-6">
            <div className="rounded-lg bg-white p-6 ring-1 ring-inset ring-gray-200">
              <h2 className="text-base font-semibold text-gray-900 mb-2">Platform Totals</h2>
              <p className="text-sm text-gray-500 mb-4">Current aggregates from the latest snapshot</p>
              
              {data.length > 0 ? (() => {
                const latest = data[data.length - 1];
                return (
                  <dl className="grid grid-cols-2 gap-4">
                    <div className="bg-gray-50 p-4 rounded text-center ring-1 ring-inset ring-gray-100">
                      <dt className="text-xs font-medium text-gray-500 uppercase">Total Stalls</dt>
                      <dd className="mt-1 text-2xl font-semibold text-gray-900">{latest.total_stalls}</dd>
                    </div>
                    <div className="bg-gray-50 p-4 rounded text-center ring-1 ring-inset ring-gray-100">
                      <dt className="text-xs font-medium text-gray-500 uppercase">Assessed</dt>
                      <dd className="mt-1 text-2xl font-semibold text-gray-900">{latest.assessed_stalls}</dd>
                    </div>
                    <div className="bg-gray-50 p-4 rounded text-center ring-1 ring-inset ring-gray-100">
                      <dt className="text-xs font-medium text-gray-500 uppercase">Total Flagged</dt>
                      <dd className="mt-1 text-2xl font-semibold text-red-600">{latest.flagged_stalls}</dd>
                    </div>
                    <div className="bg-gray-50 p-4 rounded text-center ring-1 ring-inset ring-gray-100">
                      <dt className="text-xs font-medium text-gray-500 uppercase">Global Avg Score</dt>
                      <dd className="mt-1 text-2xl font-semibold text-blue-600">
                        {latest.average_score ? latest.average_score.toFixed(1) : "—"}
                      </dd>
                    </div>
                  </dl>
                );
              })() : (
                <p className="text-sm text-gray-500">No data available.</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
