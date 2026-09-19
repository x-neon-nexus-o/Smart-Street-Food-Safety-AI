/**
 * Typed fetch wrapper for the FastAPI backend.
 *
 * Every call attaches the bearer token from the auth cookie and normalises
 * FastAPI's error shapes (`{detail: "..."}` and the 422
 * `{detail: [{loc, msg, ...}]}` validation form) into a single ApiError, so
 * callers never have to branch on error format.
 */

import { clearToken, getToken } from "./auth";
import type {
  CurrentUser,
  HygieneCheck,
  HygieneCheckSummary,
  HygieneConfig,
  PublicStallProfile,
  ScanResult,
  Stall,
  StallQr,
  Token,
  UserRole,
  Vendor,
  VendorOnboardRequest,
  VendorOnboardResponse,
  ViewCategory,
} from "./types";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "";

export const API_V1_URL = `${API_BASE_URL}/api/v1`;

/**
 * Shared authenticated fetch wrapper.
 *
 * Exported so feature modules can build their own typed clients on the same
 * error handling and token attachment, rather than each re-implementing
 * fetch. See lib/reviewerApi.ts.
 */
export async function apiRequest<T>(
  path: string,
  options: RequestOptions = {}
): Promise<T> {
  return request<T>(path, options);
}

export class ApiError extends Error {
  readonly status: number;
  readonly isNetworkError: boolean;

  constructor(message: string, status: number, isNetworkError = false) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.isNetworkError = isNetworkError;
  }
}

/** Flatten FastAPI's error shapes into one readable string. */
function extractDetail(body: unknown): string | null {
  if (typeof body !== "object" || body === null) return null;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === "object" && item !== null) {
          const msg = (item as { msg?: unknown }).msg;
          const loc = (item as { loc?: unknown }).loc;
          const field = Array.isArray(loc) ? loc[loc.length - 1] : undefined;
          return field ? `${field}: ${msg}` : String(msg ?? "");
        }
        return String(item);
      })
      .filter(Boolean);
    return messages.length ? messages.join("; ") : null;
  }
  // The scan endpoint raises HTTPException(detail={"detail": ..., "retryable": ...})
  // so that a client can distinguish "retry might work" from "this will never
  // work". FastAPI serialises that as {"detail": {"detail": "...", ...}}.
  if (typeof detail === "object" && detail !== null) {
    const nested = (detail as { detail?: unknown }).detail;
    if (typeof nested === "string") return nested;
  }
  return null;
}

interface RequestOptions extends Omit<RequestInit, "body"> {
  /** Serialised to JSON automatically. */
  body?: unknown;
  /** Pre-built body (FormData, URLSearchParams). Sent as-is so the browser
   * sets the correct Content-Type and multipart boundary. */
  rawBody?: BodyInit;
  auth?: boolean;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {  const { body, rawBody, auth = true, headers, ...rest } = options;

  const finalHeaders = new Headers(headers);
  if (rawBody === undefined && body !== undefined) {
    finalHeaders.set("Content-Type", "application/json");
  }
  if (auth) {
    const token = getToken();
    if (token) finalHeaders.set("Authorization", `Bearer ${token}`);
  }

  let response: Response;
  try {
    response = await fetch(`${API_V1_URL}${path}`, {
      ...rest,
      headers: finalHeaders,
      body: rawBody ?? (body === undefined ? undefined : JSON.stringify(body)),
    });
  } catch {
    // fetch only rejects on network/CORS failure, which is worth
    // distinguishing: the mobile client surfaces "check your connection"
    // rather than "something went wrong".
    throw new ApiError(
      "Could not reach the server. Check your connection and try again.",
      0,
      true
    );
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = text;
    }
  }

  if (!response.ok) {
    // An expired or revoked token should not leave a dead session in the
    // cookie, or every subsequent call fails the same way.
    if (response.status === 401) clearToken();
    throw new ApiError(
      extractDetail(parsed) ?? `Request failed (${response.status})`,
      response.status
    );
  }

  return parsed as T;
}

export const api = {
  // --- Auth ---
  async login(email: string, password: string): Promise<Token> {
    // OAuth2PasswordRequestForm is form-encoded, not JSON.
    const form = new URLSearchParams({ username: email, password });
    return request<Token>("/login/access-token", {
      method: "POST",
      rawBody: form,
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      auth: false,
    });
  },

  async loginWithGoogle(token: string): Promise<Token> {
    return request<Token>("/google", {
      method: "POST",
      body: { token },
      auth: false,
    });
  },

  async loginWithDigilocker(code: string): Promise<Token> {
    return request<Token>("/digilocker", {
      method: "POST",
      body: { code },
      auth: false,
    });
  },

  async register(input: {
    email: string;
    password: string;
    full_name?: string;
    role?: UserRole;
  }): Promise<CurrentUser> {
    return request<CurrentUser>("/register", {
      method: "POST",
      body: input,
      auth: false,
    });
  },

  async me(): Promise<CurrentUser> {
    return request<CurrentUser>("/me");
  },

  // --- Vendor / stall ---
  async onboardVendor(
    payload: VendorOnboardRequest
  ): Promise<VendorOnboardResponse> {
    return request<VendorOnboardResponse>("/vendors/onboard", {
      method: "POST",
      body: payload,
    });
  },

  async myVendorProfile(): Promise<Vendor> {
    return request<Vendor>("/vendors/me");
  },

  async myStalls(): Promise<Stall[]> {
    return request<Stall[]>("/stalls/mine");
  },

  async getStall(stallId: number): Promise<Stall> {
    return request<Stall>(`/stalls/${stallId}`);
  },

  async getStallQr(stallId: number): Promise<StallQr> {
    return request<StallQr>(`/stalls/${stallId}/qr`);
  },

  // --- Product scan ---
  /**
   * Upload a label photo and get a verdict back.
   *
   * Synchronous: the response is the finished result card, so the UI shows a
   * loading state for the duration. See backend/services/products/
   * scan_service.py for the pipeline.
   */
  async scanLabel(input: {
    stallId: number;
    image: Blob;
    fileName?: string;
    language?: string;
  }): Promise<ScanResult> {
    const base64 = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.onerror = reject;
      reader.readAsDataURL(input.image);
    });

    return request<ScanResult>("/products/scan-json", {
      method: "POST",
      body: {
        stall_id: input.stallId,
        file_base64: base64,
        filename: input.fileName ?? `label-${Date.now()}.jpg`,
        language: input.language
      },
    });
  },

  async scanHistory(stallId?: number, limit = 20): Promise<ScanResult[]> {
    const params = new URLSearchParams({ limit: String(limit) });
    if (stallId !== undefined) params.set("stall_id", String(stallId));
    return request<ScanResult[]>(`/products/scans?${params}`);
  },

  // --- Hygiene ---
  /**
   * Capture-flow configuration from the server.
   *
   * Fetched rather than hardcoded so adding a view or a checklist item does
   * not require a frontend release.
   */
  async hygieneConfig(): Promise<HygieneConfig> {
    return request<HygieneConfig>("/hygiene/config");
  },

  async startHygieneCheck(stallId: number): Promise<HygieneCheck> {
    // Form-encoded: the endpoint takes a Form field, matching how the
    // image upload sends its metadata.
    const form = new FormData();
    form.append("stall_id", String(stallId));
    return request<HygieneCheck>("/hygiene/checks", {
      method: "POST",
      rawBody: form,
    });
  },

  /**
   * Upload one view photo.
   *
   * Rejects a photo that duplicates another view in the same check, and
   * returns the updated coverage so the caller knows which view is next.
   */
  async uploadHygieneView(input: {
    checkId: number;
    view: ViewCategory;
    image: Blob;
    fileName?: string;
  }): Promise<HygieneCheck> {
    const base64 = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.onerror = reject;
      reader.readAsDataURL(input.image);
    });

    return request<HygieneCheck>(
      `/hygiene/checks/${input.checkId}/images-json`,
      {
        method: "POST",
        body: {
          view_category: input.view,
          file_base64: base64
        },
      }
    );
  },

  async submitHygieneChecklist(
    checkId: number,
    answers: Record<string, boolean>
  ): Promise<HygieneCheck> {
    return request<HygieneCheck>(`/hygiene/checks/${checkId}/checklist`, {
      method: "POST",
      body: { answers },
    });
  },

  async completeHygieneCheck(checkId: number): Promise<HygieneCheck> {
    return request<HygieneCheck>(`/hygiene/checks/${checkId}/complete`, {
      method: "POST",
    });
  },

  async hygieneHistory(options?: {
    stallId?: number;
    includeUnfinished?: boolean;
    limit?: number;
  }): Promise<HygieneCheckSummary[]> {
    const params = new URLSearchParams({
      limit: String(options?.limit ?? 30),
      include_unfinished: String(options?.includeUnfinished ?? false),
    });
    if (options?.stallId !== undefined) {
      params.set("stall_id", String(options.stallId));
    }
    return request<HygieneCheckSummary[]>(`/hygiene/checks?${params}`);
  },

  async getHygieneCheck(checkId: number): Promise<HygieneCheck> {
    return request<HygieneCheck>(`/hygiene/checks/${checkId}`);
  },
};

/**
 * Resolve an absolute URL for a stored scan image.
 *
 * The backend returns a root-relative path, so it must be joined to the API
 * origin rather than the Next.js origin.
 */
export function resolveImageUrl(path: string | null): string | null {
  if (!path) return null;
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  return `${API_BASE_URL}${path.startsWith("/") ? "" : "/"}${path}`;
}

/**
 * Fetch a stall's QR code PNG as a Blob.
 *
 * Needed because the QR image endpoint is authenticated: a plain
 * `<img src="...">` or `<a download href="...">` cannot attach the bearer
 * token, so the image would 401. Fetching it explicitly and handing the
 * caller an object URL is the price of keeping that endpoint closed.
 *
 * Keeping it authenticated matters: `/stalls/{id}/qr.png` is keyed by the
 * stall's serial id. If it were public, anyone could walk the id space,
 * harvest every QR, and from each one recover the public code -- reopening
 * exactly the enumeration hole the code-in-URL design closes.
 */
export async function fetchQrBlob(stallId: number): Promise<Blob> {
  const token = getToken();
  const headers = new Headers();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let response: Response;
  try {
    response = await fetch(`${API_V1_URL}/stalls/${stallId}/qr.png`, { headers });
  } catch (err: unknown) {
    console.error("DEBUG FETCH ERROR:", err);
    console.error("FETCH URL WAS:", `${API_V1_URL}/stalls/${stallId}/qr.png`);
    throw new ApiError(
      "Could not reach the server. Check your connection and try again.",
      0,
      true
    );
  }

  if (!response.ok) {
    if (response.status === 401) clearToken();
    throw new ApiError(`Could not load the QR code (${response.status})`, response.status);
  }
  return await response.blob();
}

/**
 * Fetch a stall's public profile.
 *
 * Runs on the server (the public page is a Server Component) as well as in
 * the browser, so it deliberately does NOT go through `request()` -- there
 * is no token to attach, and adding an Authorization header to a public
 * call would be misleading about what the endpoint requires.
 *
 * Returns `null` for a 404 (unknown or revoked code), which the caller
 * turns into `notFound()`. Any other failure throws, so a backend outage
 * shows an error state rather than being reported as "no such stall" --
 * those are very different things to tell someone standing at a stall.
 */
export async function fetchPublicStall(
  code: string
): Promise<PublicStallProfile | null> {
  const response = await fetch(
    `${API_V1_URL}/public/stalls/${encodeURIComponent(code)}`,
    {
      // Public, non-personal data. Matching the backend's 60s max-age keeps
      // a consumer's page fast without showing a stale score for long.
      next: { revalidate: 60 },
    }
  );

  if (response.status === 404) return null;
  if (!response.ok) {
    throw new ApiError(
      `Could not load this stall (${response.status})`,
      response.status
    );
  }
  return (await response.json()) as PublicStallProfile;
}

/**
 * Fetch all public stalls for the consumer map.
 * Runs in the browser or server.
 */
export async function fetchPublicStallsMap(): Promise<import("./types").PublicStallLocation[]> {
  const response = await fetch(`${API_V1_URL}/public/stalls`, {
    next: { revalidate: 60 },
  });

  if (!response.ok) {
    throw new ApiError(
      `Could not load map data (${response.status})`,
      response.status
    );
  }
  return await response.json();
}

/**
 * Submit a consumer concern report.
 */
export async function reportConcern(
  code: string,
  category: string,
  notes?: string
): Promise<{ message: string }> {
  const response = await fetch(`${API_V1_URL}/public/stalls/${encodeURIComponent(code)}/report`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ category, notes }),
  });

  if (!response.ok) {
    throw new ApiError(
      `Failed to submit report (${response.status})`,
      response.status
    );
  }
  return await response.json();
}
