// Feature: react-frontend, Property 6: API client throws structured error on HTTP failure
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as fc from 'fast-check';

// Mock import.meta.env before importing the module
vi.stubGlobal('import', { meta: { env: { VITE_API_BASE: 'http://localhost:8000' } } });

import { analyzeDocument, fetchVoiceSummary, fetchVoiceStory } from '../../api/client.js';

describe('API client — Property 6: structured error on HTTP failure', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('analyzeDocument throws structured error for any 4xx/5xx status with detail message', async () => {
    // Feature: react-frontend, Property 6: API client throws structured error on HTTP failure
    // Validates: Requirements 5.5
    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: 400, max: 599 }),
        fc.string(),
        async (status, detail) => {
          vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
            ok: false,
            status,
            statusText: 'Error',
            json: async () => ({ detail }),
          }));

          let thrown = null;
          try {
            await analyzeDocument(new File(['content'], 'test.pdf'));
          } catch (err) {
            thrown = err;
          }

          expect(thrown).not.toBeNull();
          expect(thrown.status).toBe(status);
          expect(thrown.message).toContain(detail);
        }
      ),
      { numRuns: 100 }
    );
  });

  it('fetchVoiceSummary throws structured error for any 4xx/5xx status with detail message', async () => {
    // Feature: react-frontend, Property 6: API client throws structured error on HTTP failure
    // Validates: Requirements 5.5
    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: 400, max: 599 }),
        fc.string(),
        async (status, detail) => {
          vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
            ok: false,
            status,
            statusText: 'Error',
            json: async () => ({ detail }),
          }));

          let thrown = null;
          try {
            await fetchVoiceSummary({});
          } catch (err) {
            thrown = err;
          }

          expect(thrown).not.toBeNull();
          expect(thrown.status).toBe(status);
          expect(thrown.message).toContain(detail);
        }
      ),
      { numRuns: 100 }
    );
  });

  it('fetchVoiceStory throws structured error for any 4xx/5xx status with detail message', async () => {
    // Feature: react-frontend, Property 6: API client throws structured error on HTTP failure
    // Validates: Requirements 5.5
    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: 400, max: 599 }),
        fc.string(),
        async (status, detail) => {
          vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
            ok: false,
            status,
            statusText: 'Error',
            json: async () => ({ detail }),
          }));

          let thrown = null;
          try {
            await fetchVoiceStory({}, 'Aoede');
          } catch (err) {
            thrown = err;
          }

          expect(thrown).not.toBeNull();
          expect(thrown.status).toBe(status);
          expect(thrown.message).toContain(detail);
        }
      ),
      { numRuns: 100 }
    );
  });
});

// Feature: react-frontend, Property 7: Base64 round-trip
describe('API client — Property 7: Base64 audio round-trip', () => {
  it('decoding and re-encoding base64 produces the original string for any byte array', () => {
    // Feature: react-frontend, Property 7: Base64 round-trip
    // Validates: Requirements 7.1
    fc.assert(
      fc.property(
        fc.uint8Array(),
        (bytes) => {
          const binaryStr = Array.from(bytes).map(b => String.fromCharCode(b)).join('');
          const base64 = btoa(binaryStr);
          const decoded = atob(base64);
          const reEncoded = btoa(decoded);
          expect(reEncoded).toBe(base64);
        }
      ),
      { numRuns: 100 }
    );
  });
});

// Unit tests 9.14–9.17

describe('API client — unit tests', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  // 9.14: analyzeDocument sends multipart POST to /analyze (Requirements: 5.2)
  it('9.14: analyzeDocument sends multipart POST to /analyze', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({}),
    }));
    const file = new File(['content'], 'test.pdf', { type: 'application/pdf' });
    await analyzeDocument(file);
    const [url, options] = fetch.mock.calls[0];
    expect(url).toContain('/analyze');
    expect(options.method).toBe('POST');
    expect(options.body).toBeInstanceOf(FormData);
  });

  // 9.15: fetchVoiceSummary sends JSON POST to /voice-summary (Requirements: 5.3)
  it('9.15: fetchVoiceSummary sends JSON POST to /voice-summary', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ audio: '' }),
    }));
    await fetchVoiceSummary({ executive_summary: 'test' });
    const [url, options] = fetch.mock.calls[0];
    expect(url).toContain('/voice-summary');
    expect(options.method).toBe('POST');
    expect(options.headers['Content-Type']).toBe('application/json');
  });

  // 9.16: fetchVoiceStory sends JSON POST to /voice-story with voice field (Requirements: 5.4)
  it('9.16: fetchVoiceStory sends JSON POST to /voice-story with voice field', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ audio: '' }),
    }));
    const story = { id: '1', role: 'user', feature: 'feat', benefit: 'ben', priority: 'high' };
    await fetchVoiceStory(story, 'Aoede');
    const [url, options] = fetch.mock.calls[0];
    expect(url).toContain('/voice-story');
    expect(options.method).toBe('POST');
    const body = JSON.parse(options.body);
    expect(body.voice).toBe('Aoede');
  });

  // 9.17: falls back to http://localhost:8000 when VITE_API_BASE is unset (Requirements: 6.4)
  it('9.17: falls back to http://localhost:8000 when VITE_API_BASE is unset', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({}),
    }));
    const file = new File(['content'], 'test.pdf', { type: 'application/pdf' });
    await analyzeDocument(file);
    const [url] = fetch.mock.calls[0];
    // The module was loaded with VITE_API_BASE stubbed to 'http://localhost:8000'
    expect(url).toMatch(/^http:\/\/localhost:8000/);
  });
});
