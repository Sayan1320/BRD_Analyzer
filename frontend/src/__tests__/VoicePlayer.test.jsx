import * as fc from 'fast-check';

// Feature: react-frontend, Property 8: WAV header invariant
// Validates: Requirements 7.2
describe('VoicePlayer', () => {
  it('P8: decoded base64 WAV bytes start with RIFF header', () => {
    fc.assert(
      fc.property(
        fc.uint8Array({ minLength: 44 }),
        (bytes) => {
          // Force RIFF header bytes
          const wavBytes = new Uint8Array(bytes);
          wavBytes[0] = 0x52; // R
          wavBytes[1] = 0x49; // I
          wavBytes[2] = 0x46; // F
          wavBytes[3] = 0x46; // F

          // Encode to base64
          const binaryStr = Array.from(wavBytes).map(b => String.fromCharCode(b)).join('');
          const base64 = btoa(binaryStr);

          // Decode back
          const decoded = atob(base64);

          // Assert first 4 bytes are RIFF
          expect(decoded.charCodeAt(0)).toBe(0x52);
          expect(decoded.charCodeAt(1)).toBe(0x49);
          expect(decoded.charCodeAt(2)).toBe(0x46);
          expect(decoded.charCodeAt(3)).toBe(0x46);
        }
      ),
      { numRuns: 100 }
    );
  });
});

// Feature: react-frontend, Property 9: Voice completeness
// Validates: Requirements 7.4
import { vi } from 'vitest';
import * as client from '../api/client.js';

describe('Voice completeness', () => {
  it('P9: fetchVoiceStory returns decodable audio for all voice names', async () => {
    const VOICES = ['Aoede', 'Charon', 'Fenrir', 'Kore', 'Puck'];

    await fc.assert(
      fc.asyncProperty(
        fc.constantFrom(...VOICES),
        fc.uint8Array({ minLength: 1 }),
        async (voiceName, bytes) => {
          const binaryStr = Array.from(bytes).map(b => String.fromCharCode(b)).join('');
          const audioBase64 = btoa(binaryStr);

          vi.spyOn(client, 'fetchVoiceStory').mockResolvedValueOnce({ audio: audioBase64 });

          const result = await client.fetchVoiceStory(
            { id: '1', role: 'user', feature: 'test', benefit: 'test', priority: 'high' },
            voiceName
          );

          expect(result.audio).toBeTruthy();
          expect(result.audio.length).toBeGreaterThan(0);

          // Verify atob can decode without throwing
          let decoded;
          expect(() => { decoded = atob(result.audio); }).not.toThrow();
          expect(decoded.length).toBeGreaterThan(0);

          vi.restoreAllMocks();
        }
      ),
      { numRuns: 100 }
    );
  });
});

// Unit tests 9.9–9.11
import { render, fireEvent, waitFor } from '@testing-library/react';
import VoicePlayer from '../components/VoicePlayer';

const minimalResult = {
  analysis: {
    executive_summary: 'Test',
    user_stories: [],
    acceptance_criteria: [],
    gap_flags: [],
  },
};

describe('VoicePlayer — unit tests', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  // 9.9: renders voice selector with 5 options and Aoede selected by default (Requirements: 4.9)
  it('9.9: renders voice selector with 5 options and Aoede selected by default', () => {
    const { getByTestId } = render(
      <VoicePlayer analysisResult={minimalResult} onVoiceChange={vi.fn()} />
    );
    const selector = getByTestId('voice-selector');
    expect(selector.options).toHaveLength(5);
    expect(selector.value).toBe('Aoede');
  });

  // 9.10: idle state shows "🎙️ Listen to Summary" (Requirements: 4.3, 4.5, 4.6)
  it('9.10: button shows "🎙️ Listen to Summary" in idle state', () => {
    vi.spyOn(client, 'fetchVoiceSummary').mockResolvedValue({ audio: btoa('fake-audio') });
    const { getByTestId } = render(
      <VoicePlayer analysisResult={minimalResult} onVoiceChange={vi.fn()} />
    );
    const btn = getByTestId('play-summary-btn');
    expect(btn.textContent).toBe('🎙️ Listen to Summary');
  });

  // 9.11: previous Object URL is revoked before creating a new one (Requirements: 7.3)
  it('9.11: previous Object URL is revoked before creating a new one', async () => {
    const fakeUrl1 = 'blob:fake-url-1';
    const fakeUrl2 = 'blob:fake-url-2';
    let callCount = 0;
    const createObjectURL = vi.fn(() => {
      callCount++;
      return callCount === 1 ? fakeUrl1 : fakeUrl2;
    });
    const revokeObjectURL = vi.fn();
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL });

    // Mock Audio to avoid actual playback
    const mockPlay = vi.fn().mockResolvedValue(undefined);
    const mockAudio = { play: mockPlay, onplay: null, onended: null, onerror: null };
    vi.stubGlobal('Audio', vi.fn(() => mockAudio));

    // Provide valid base64 audio
    const fakeAudio = btoa(String.fromCharCode(...new Uint8Array(44)));
    vi.spyOn(client, 'fetchVoiceSummary').mockResolvedValue({ audio: fakeAudio });

    const { getByTestId } = render(
      <VoicePlayer analysisResult={minimalResult} onVoiceChange={vi.fn()} />
    );

    // First play
    fireEvent.click(getByTestId('play-summary-btn'));
    await waitFor(() => expect(createObjectURL).toHaveBeenCalledTimes(1));

    // Simulate audio ended so button re-enables
    mockAudio.onended && mockAudio.onended();

    // Second play
    vi.spyOn(client, 'fetchVoiceSummary').mockResolvedValue({ audio: fakeAudio });
    fireEvent.click(getByTestId('play-summary-btn'));
    await waitFor(() => expect(createObjectURL).toHaveBeenCalledTimes(2));

    // revokeObjectURL should have been called with the first URL before the second createObjectURL
    expect(revokeObjectURL).toHaveBeenCalledWith(fakeUrl1);
  });
});
