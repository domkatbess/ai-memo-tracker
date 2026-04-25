/**
 * API client for communicating with the Memo Tracker backend.
 *
 * All requests go through API Gateway over HTTPS.
 * Token management and offline queuing will be implemented in a later task.
 */

const API_BASE_URL = ''; // Set via environment config

export interface ApiResponse<T = unknown> {
  statusCode: number;
  body: T;
}

/**
 * Generic request helper. Placeholder — full implementation in task 10.5.
 */
export async function apiRequest<T = unknown>(
  method: string,
  path: string,
  body?: Record<string, unknown>,
): Promise<ApiResponse<T>> {
  const url = `${API_BASE_URL}${path}`;
  const response = await fetch(url, {
    method,
    headers: {
      'Content-Type': 'application/json',
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json();
  return { statusCode: response.status, body: data as T };
}

export default { apiRequest };
