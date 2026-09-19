"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { PublicStallLocation, ScoreBand } from "@/lib/types";
import { fetchPublicStallsMap } from "@/lib/api";

// Dynamically import the map component so Leaflet only runs on the client.
const HygieneMap = dynamic(() => import("@/components/consumer/HygieneMap"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full w-full items-center justify-center bg-brand-bg">
      <div className="text-[11px] font-bold text-text-primary/50 font-['Plus_Jakarta_Sans'] uppercase tracking-widest">Loading map...</div>
    </div>
  ),
});

export default function ConsumerHome() {
  const [stalls, setStalls] = useState<PublicStallLocation[]>([]);
  const [filter, setFilter] = useState<ScoreBand | "all">("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadStalls() {
      try {
        const data = await fetchPublicStallsMap();
        setStalls(data);
      } catch (err: unknown) {
        setError((err instanceof Error ? err.message : String(err)) || "Failed to load stalls.");
      } finally {
        setLoading(false);
      }
    }
    loadStalls();
  }, []);

  const filteredStalls = stalls.filter((stall) => {
    if (filter === "all") return true;
    return stall.band === filter;
  });

  return (
    <div className="flex h-full min-h-screen flex-col">
      {/* Header & Filters */}
      <div className="bg-white p-4 shadow-[0_2px_8px_rgba(16,34,15,0.06)] z-10 relative border-b border-border-default/10">
        <h1 className="text-2xl font-extrabold text-text-primary font-['Plus_Jakarta_Sans']">Food Safety Map</h1>
        <p className="mt-1 text-[13px] font-medium text-text-primary/60 font-['Inter']">
          Find nearby stalls and their hygiene scores.
        </p>

        <div className="mt-3 flex gap-2 overflow-x-auto pb-1 hide-scrollbar">
          {(["all", "good", "fair", "poor", "bad"] as const).map((band) => (
            <button
              key={band}
              onClick={() => setFilter(band)}
              className={`shrink-0 rounded-full px-4 py-2 text-[11px] font-bold tracking-wide font-['Plus_Jakarta_Sans'] ring-1 ring-inset transition-colors ${
                filter === band
                  ? "bg-surface-dark text-text-inverse ring-surface-dark shadow-[0_2px_8px_rgba(11,69,22,0.2)]"
                  : "bg-white text-text-primary ring-border-default/20 hover:bg-surface-soft"
              }`}
            >
              {band === "all"
                ? "All Stalls"
                : band === "good"
                ? "High (80-100)"
                : band === "fair"
                ? "Moderate (60-79)"
                : band === "poor"
                ? "Needs improvement (40-59)"
                : "Low (0-39)"}
            </button>
          ))}
        </div>
      </div>

      {/* Map Area */}
      <div className="flex-1 relative z-0 min-h-0">
        {loading ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-[11px] font-bold text-text-primary/50 font-['Plus_Jakarta_Sans'] uppercase tracking-widest">Loading stalls...</div>
          </div>
        ) : error ? (
          <div className="flex h-full items-center justify-center p-6 text-center">
            <div className="text-sm font-bold text-[#E53935] font-['Plus_Jakarta_Sans']">{error}</div>
          </div>
        ) : (
          <HygieneMap stalls={filteredStalls} />
        )}
      </div>
      
      <style dangerouslySetInnerHTML={{__html: `
        .hide-scrollbar::-webkit-scrollbar {
          display: none;
        }
        .hide-scrollbar {
          -ms-overflow-style: none;
          scrollbar-width: none;
        }
      `}} />
    </div>
  );
}
