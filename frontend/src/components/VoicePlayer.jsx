import { useState, useRef } from 'react';
import { fetchVoiceSummary } from '../api/client';

const VOICES = ['Aoede', 'Charon', 'Fenrir', 'Kore', 'Puck'];

export default function VoicePlayer({ analysisResult, onVoiceChange }) {
  const [selectedVoice, setSelectedVoice] = useState('Aoede');
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryPlaying, setSummaryPlaying] = useState(false);
  const [summaryError, setSummaryError] = useState(null);
  const objectUrlRef = useRef(null);

  function handleVoiceChange(e) {
    const voice = e.target.value;
    setSelectedVoice(voice);
    if (onVoiceChange) onVoiceChange(voice);
  }

  async function handleSummaryPlay() {
    setSummaryLoading(true);
    setSummaryError(null);
    try {
      const response = await fetchVoiceSummary(analysisResult);
      const audioBase64 = response.audio;

      // Decode base64 to Blob
      const binaryStr = atob(audioBase64);
      const bytes = new Uint8Array(binaryStr.length).map((_, i) => binaryStr.charCodeAt(i));
      const blob = new Blob([bytes], { type: 'audio/wav' });

      // Revoke previous Object URL to prevent memory leaks
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);

      // Create new Object URL and play
      objectUrlRef.current = URL.createObjectURL(blob);
      const audio = new Audio(objectUrlRef.current);

      audio.onplay = () => setSummaryPlaying(true);
      audio.onended = () => {
        setSummaryPlaying(false);
        setSummaryLoading(false);
      };
      audio.onerror = () => {
        setSummaryPlaying(false);
        setSummaryLoading(false);
        setSummaryError('Audio playback failed.');
      };

      audio.play();
    } catch (err) {
      setSummaryLoading(false);
      setSummaryError(err.message || 'Failed to fetch audio.');
    }
  }

  const isDisabled = summaryLoading || summaryPlaying;

  return (
    <div className="voice-player">
      {/* Voice selector */}
      <div className="voice-selector">
        <label htmlFor="voice-select">Voice:</label>
        <select
          id="voice-select"
          data-testid="voice-selector"
          value={selectedVoice}
          onChange={handleVoiceChange}
        >
          {VOICES.map((v) => (
            <option key={v} value={v}>{v}</option>
          ))}
        </select>
      </div>

      {/* Summary play button */}
      <button
        data-testid="play-summary-btn"
        onClick={handleSummaryPlay}
        disabled={isDisabled}
        aria-busy={summaryLoading}
      >
        {summaryPlaying ? '🔊 Playing...' : summaryLoading ? '⏳ Loading...' : '🎙️ Listen to Summary'}
      </button>

      {/* Playing indicator */}
      {summaryPlaying && (
        <span data-testid="playing-indicator">🔊 Playing...</span>
      )}

      {/* Error message */}
      {summaryError && (
        <p data-testid="voice-error" role="alert">{summaryError}</p>
      )}
    </div>
  );
}
