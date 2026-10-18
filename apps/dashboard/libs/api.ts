export const API_BASE = process.env.INTERNAL_API_URL || process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

export async function fetchAPI(endpoint: string) {
  const headers: HeadersInit = {
    Accept: 'application/json',
  };
  const apiKey = process.env.API_READ_KEY || process.env.API_SECRET_KEY || process.env.API_ADMIN_KEY;
  if (apiKey) {
    headers['Authorization'] = `Bearer ${apiKey}`;
  }
  const res = await fetch(`${API_BASE}${endpoint}`, { cache: 'no-store', headers });
  if (!res.ok) {
    throw new Error(`API error: ${res.statusText} (${res.status}) on ${endpoint}`);
  }
  const json = await res.json();
  return json.data;
}
