/**
 * Typed client for the reviewer dashboard endpoints.
 *
 * Built on the shared `apiRequest` wrapper so token handling and FastAPI
 * error normalisation stay in one place. Kept separate from lib/api.ts
 * because this is a distinct surface (desktop-only, reviewer-only) rather
 * than part of the vendor/consumer client.
 */

import { apiRequest } from "./api";
import type {
  FlagListResponse,
  FlagRecord,
  FlagStatus,
  ReviewerSummary,
  ReviewSort,
  VendorDetail,
  VendorListResponse,
} from "./types";

export interface VendorQuery {
  search?: string;
  band?: string;
  flagged?: boolean;
  hasScan?: boolean;
  sort?: ReviewSort;
  order?: "asc" | "desc";
  skip?: number;
  limit?: number;
}

function vendorParams(query: VendorQuery): string {
  const params = new URLSearchParams();
  if (query.search) params.set("search", query.search);
  if (query.band) params.set("band", query.band);
  // Only sent when explicitly set: `flagged=false` and "no filter" are
  // different requests, and omitting the key is how the API distinguishes
  // them.
  if (query.flagged !== undefined) params.set("flagged", String(query.flagged));
  if (query.hasScan !== undefined) params.set("has_scan", String(query.hasScan));
  if (query.sort) params.set("sort", query.sort);
  if (query.order) params.set("order", query.order);
  if (query.skip !== undefined) params.set("skip", String(query.skip));
  if (query.limit !== undefined) params.set("limit", String(query.limit));
  return params.toString();
}

export const reviewerApi = {
  async vendors(query: VendorQuery = {}): Promise<VendorListResponse> {
    const qs = vendorParams(query);
    return apiRequest<VendorListResponse>(`/reviewer/vendors${qs ? `?${qs}` : ""}`);
  },

  async summary(): Promise<ReviewerSummary> {
    return apiRequest<ReviewerSummary>("/reviewer/summary");
  },

  async vendorDetail(stallId: number): Promise<VendorDetail> {
    return apiRequest<VendorDetail>(`/reviewer/vendors/${stallId}`);
  },

  async flags(options: {
    status?: FlagStatus;
    skip?: number;
    limit?: number;
  } = {}): Promise<FlagListResponse> {
    const params = new URLSearchParams();
    if (options.status) params.set("status", options.status);
    if (options.skip !== undefined) params.set("skip", String(options.skip));
    if (options.limit !== undefined) params.set("limit", String(options.limit));
    const qs = params.toString();
    return apiRequest<FlagListResponse>(`/reviewer/flags${qs ? `?${qs}` : ""}`);
  },

  async createFlag(stallId: number, reason: string): Promise<FlagRecord> {
    return apiRequest<FlagRecord>(`/reviewer/vendors/${stallId}/flags`, {
      method: "POST",
      body: { reason },
    });
  },

  async resolveFlag(flagId: number, note?: string): Promise<FlagRecord> {
    return apiRequest<FlagRecord>(`/reviewer/flags/${flagId}/resolve`, {
      method: "POST",
      body: { note: note || null },
    });
  },

  async audit(skip = 0, limit = 50): Promise<{ items: unknown[]; total: number }> {
    const params = new URLSearchParams({ skip: String(skip), limit: String(limit) });
    return apiRequest<{ items: unknown[]; total: number }>(`/reviewer/audit?${params}`);
  },

  async analytics(days = 30): Promise<{ items: unknown[] }> {
    const params = new URLSearchParams({ days: String(days) });
    return apiRequest<{ items: unknown[] }>(`/reviewer/analytics?${params}`);
  },

  async scanDetail(scanId: number): Promise<import("./types").ScanResult> {
    // Falls back to the shared products API which reviewers have access to
    return apiRequest<import("./types").ScanResult>(`/products/scans/${scanId}`);
  }
};
