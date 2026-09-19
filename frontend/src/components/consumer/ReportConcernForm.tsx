"use client";

import { useState } from "react";
import { reportConcern } from "@/lib/api";

interface ReportConcernFormProps {
  stallCode: string;
}

export default function ReportConcernForm({ stallCode }: ReportConcernFormProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [category, setCategory] = useState("hygiene");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await reportConcern(stallCode, category, notes);
      setSuccess(true);
      // Close automatically after 3s
      setTimeout(() => {
        setIsOpen(false);
        setSuccess(false);
        setNotes("");
        setCategory("hygiene");
      }, 3000);
    } catch (err: unknown) {
      setError((err instanceof Error ? err.message : String(err)) || "Failed to submit report. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  if (!isOpen) {
    return (
      <div className="mt-8 mb-4 flex justify-center">
        <button
          onClick={() => setIsOpen(true)}
          className="text-xs font-semibold text-gray-500 hover:text-gray-700 underline"
        >
          Report a Concern
        </button>
      </div>
    );
  }

  return (
    <div className="mt-6 rounded-2xl bg-white p-5 ring-1 ring-inset ring-gray-200">
      <h2 className="text-sm font-semibold text-gray-900 mb-4">Report a Concern</h2>
      
      {success ? (
        <div className="rounded-xl bg-emerald-50 p-3 text-sm text-emerald-900 ring-1 ring-inset ring-emerald-200">
          Thank you for your report. It has been submitted for review.
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">
              Category
            </label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="w-full rounded-xl border-0 px-3 py-2 text-sm text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-blue-600"
            >
              <option value="hygiene">Hygiene condition looks different</option>
              <option value="info">Stall information incorrect</option>
              <option value="location">Location incorrect</option>
              <option value="other">Other concern</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">
              Details (Optional)
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
              placeholder="Please provide more details..."
              className="w-full rounded-xl border-0 px-3 py-2 text-sm text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-blue-600 resize-none"
            />
          </div>

          {error && (
            <p className="text-xs text-red-600">{error}</p>
          )}

          <div className="flex gap-2 pt-2">
            <button
              type="submit"
              disabled={submitting}
              className="flex-1 rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-500 disabled:opacity-50"
            >
              {submitting ? "Submitting..." : "Submit Report"}
            </button>
            <button
              type="button"
              onClick={() => setIsOpen(false)}
              className="flex-1 rounded-xl bg-white px-4 py-2 text-sm font-semibold text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50"
            >
              Cancel
            </button>
          </div>

          <p className="mt-2 text-[10px] text-gray-500 text-center">
            Note: Consumers cannot directly modify hygiene scores. Reports are reviewed by administrators.
          </p>
        </form>
      )}
    </div>
  );
}
