export const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

export async function fetchAPI(endpoint: string) {
  const headers: HeadersInit = {};
  const apiSecret = process.env.API_SECRET_KEY;
  if (apiSecret) {
    headers.Authorization = `Bearer ${apiSecret}`;
  }
  const res = await fetch(`${API_BASE}${endpoint}`, { cache: 'no-store', headers });
  if (!res.ok) {
    throw new Error(`API error: ${res.statusText}`);
  }
  const json = await res.json();
  return json.data;
}
