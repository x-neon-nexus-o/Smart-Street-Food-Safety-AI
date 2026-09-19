"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { bandStyle } from "@/lib/hygieneStyles";
import type { Stall, HygieneCheckSummary } from "@/lib/types";

export default function VendorDashboard() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [stall, setStall] = useState<Stall | null>(null);
  const [history, setHistory] = useState<HygieneCheckSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadDashboard() {
      try {
        const me = await api.me();
        if (me.vendor_id === null) {
          router.replace("/vendor/profile/edit");
          return;
        }

        const stalls = await api.myStalls();
        if (stalls.length === 0) {
          router.replace("/vendor/profile/edit");
          return;
        }
        
        setStall(stalls[0]);

        // Load hygiene history for this stall
        const checks = await api.hygieneHistory({ limit: 5 });
        const scoredChecks = checks.filter(c => c.status === "scored");
        setHistory(scoredChecks);

      } catch (err: unknown) {
        if (err instanceof ApiError && err.status === 401) {
          router.replace("/login?next=/vendor");
          return;
        }
        setError(err instanceof Error ? err.message : "Could not load dashboard data.");
      } finally {
        setLoading(false);
      }
    }
    loadDashboard();
  }, [router]);

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-text-primary/40 font-['Plus_Jakarta_Sans'] font-bold" suppressHydrationWarning>
        Loading…
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-full flex-col items-center justify-center p-6 text-center">
        <p className="text-sm font-bold text-[#E53935] font-['Plus_Jakarta_Sans']">{error}</p>
      </div>
    );
  }

  if (!stall) return null;

  // Calculate scores and trends
  const latestCheck = history.length > 0 ? history[0] : null;
  const previousCheck = history.length > 1 ? history[1] : null;
  
  const latestScore = latestCheck?.final_score !== null ? Math.round(latestCheck!.final_score!) : null;
  const previousScore = previousCheck?.final_score !== null ? Math.round(previousCheck!.final_score!) : null;
  
  const scoreDiff = latestScore !== null && previousScore !== null 
    ? latestScore - previousScore 
    : null;

  const currentBandStyle = latestCheck ? bandStyle(latestCheck.band) : null;

  return (
    <div className="p-5 pb-8 min-h-screen bg-brand-bg">
      <div className="mb-6">
        <h2 className="text-[11px] font-extrabold uppercase tracking-widest text-text-primary/50 font-['Plus_Jakarta_Sans']">My Stall</h2>
        <h1 className="text-3xl font-extrabold text-text-primary font-['Plus_Jakarta_Sans']">{stall.name}</h1>
      </div>

      <div className="rounded-2xl bg-white p-6 shadow-[0_2px_8px_rgba(16,34,15,0.06)] ring-1 ring-inset ring-border-default/10 mb-6">
        <h2 className="text-sm font-extrabold text-text-primary mb-4 font-['Plus_Jakarta_Sans']">Hygiene Assessment</h2>
        
        {latestCheck && latestScore !== null ? (
          <div>
            <div className="flex items-baseline gap-3">
              <span className="text-5xl font-extrabold tabular-nums text-text-primary font-['Plus_Jakarta_Sans']">{latestScore}</span>
              <span className="text-lg font-bold text-text-primary/40 font-['Plus_Jakarta_Sans']">/100</span>
            </div>
            
            {currentBandStyle && (
              <div className={`mt-3 inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-semibold ring-1 ring-inset ${currentBandStyle.chip}`}>
                <span aria-hidden="true">{currentBandStyle.icon}</span>
                {currentBandStyle.label} hygiene score
              </div>
            )}

            {scoreDiff !== null && (
              <p className={`mt-4 text-[11px] font-bold font-['Plus_Jakarta_Sans'] ${scoreDiff > 0 ? "text-[#35C56D]" : scoreDiff < 0 ? "text-[#E53935]" : "text-text-primary/50"}`}>
                {scoreDiff > 0 ? "↑" : scoreDiff < 0 ? "↓" : "—"} {Math.abs(scoreDiff)} points from previous assessment
              </p>
            )}

            {latestCheck.indicator_count > 0 && (
              <div className="mt-5 border-t border-border-default/10 pt-4">
                <h3 className="text-[11px] font-extrabold text-text-primary/50 uppercase tracking-widest mb-2 font-['Plus_Jakarta_Sans']">Detected Issues:</h3>
                <ul className="list-disc list-inside text-[13px] font-medium text-text-primary/70 space-y-1 font-['Inter']">
                  <li>{latestCheck.indicator_count} concern{latestCheck.indicator_count > 1 ? "s" : ""} found</li>
                  {/* Detailed issues are on the specific check page */}
                  <li>
                    <Link href={`/vendor/hygiene/${latestCheck.id}`} className="font-bold text-surface-dark hover:underline font-['Plus_Jakarta_Sans']">
                      View full report
                    </Link>
                  </li>
                </ul>
              </div>
            )}
            
            <p className="mt-4 text-[10px] font-medium text-text-primary/40 font-['Inter']">
              Last assessed: {latestCheck.scored_at || latestCheck.created_at ? new Date(latestCheck.scored_at ?? latestCheck.created_at!).toLocaleDateString() : 'Unknown'}
            </p>
          </div>
        ) : (
          <div className="text-center py-4">
            <p className="text-sm font-medium text-text-primary/50 mb-2 font-['Inter']">No hygiene score yet.</p>
          </div>
        )}
      </div>

      <div className="space-y-3">
        <Link 
          href="/vendor/hygiene/new" 
          className="flex items-center justify-between rounded-2xl bg-surface-dark px-6 py-4 text-text-inverse shadow-[0_4px_12px_rgba(11,69,22,0.2)] hover:bg-[#10220F] transition-all active:scale-[0.98]"
        >
          <span className="font-extrabold font-['Plus_Jakarta_Sans']">Start Hygiene Check</span>
          <span className="text-xl">✨</span>
        </Link>
        
        <Link 
          href="/vendor/scan" 
          className="flex items-center justify-between rounded-2xl bg-white px-6 py-4 text-text-primary shadow-[0_2px_8px_rgba(16,34,15,0.06)] ring-1 ring-inset ring-border-default/10 hover:bg-surface-soft transition-all active:scale-[0.98]"
        >
          <span className="font-extrabold font-['Plus_Jakarta_Sans']">Scan Food Product</span>
          <span className="text-xl">📷</span>
        </Link>
        
        <Link 
          href="/vendor/qr" 
          className="flex items-center justify-between rounded-2xl bg-white px-6 py-4 text-text-primary shadow-[0_2px_8px_rgba(16,34,15,0.06)] ring-1 ring-inset ring-border-default/10 hover:bg-surface-soft transition-all active:scale-[0.98]"
        >
          <span className="font-extrabold font-['Plus_Jakarta_Sans']">My QR Code</span>
          <span className="text-xl">🔳</span>
        </Link>
        
        <Link 
          href="/vendor/profile/edit" 
          className="flex items-center justify-between rounded-2xl bg-white px-6 py-4 text-text-primary shadow-[0_2px_8px_rgba(16,34,15,0.06)] ring-1 ring-inset ring-border-default/10 hover:bg-surface-soft transition-all active:scale-[0.98]"
        >
          <span className="font-extrabold font-['Plus_Jakarta_Sans']">Stall Settings</span>
          <span className="text-xl">⚙️</span>
        </Link>
      </div>
    </div>
  );
}
