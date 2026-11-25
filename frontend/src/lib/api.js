/**
 * API client helpers for communicating with the FastAPI backend.
 * Uses NEXT_PUBLIC_API_URL from environment variables.
 */

const DEFAULT_API_URL = "http://localhost:8000";

export function getApiBaseUrl() {
  return (process.env.NEXT_PUBLIC_API_URL || DEFAULT_API_URL).replace(/\/+$/, "");
}

/**
 * Fetch real health and environment readiness status from the backend.
 * Throws an error if the backend is offline or returns a non-OK status.
 */
export async function fetchBackendHealth() {
  const response = await fetch(`${getApiBaseUrl()}/health`, {
    method: "GET",
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`Backend returned HTTP ${response.status}`);
  }

  return response.json();
}
