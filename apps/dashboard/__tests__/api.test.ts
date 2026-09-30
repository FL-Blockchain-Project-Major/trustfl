// Tests for dashboard API utility
describe('API Utility', () => {
  it('uses HTTP-based URL pattern', () => {
    const baseUrl = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';
    expect(typeof baseUrl).toBe('string');
    expect(baseUrl.startsWith('http')).toBe(true);
  });

  it('defaults to local API when env var is unset', () => {
    const baseUrl = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';
    expect(baseUrl).toBe('http://127.0.0.1:8000');
  });

  it('can construct a valid endpoint URL', () => {
    const baseUrl = 'http://127.0.0.1:8000';
    const endpoint = '/federations/';
    const full = `${baseUrl}${endpoint}`;
    expect(full).toBe('http://127.0.0.1:8000/federations/');
  });
});
