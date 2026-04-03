// Feature: react-frontend
// Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 10.5, 10.6, 10.12, 10.13

import { useState, useEffect } from 'react';
import FileUploader from './components/FileUploader';
import ResultsTabs from './components/ResultsTabs';
import VoicePlayer from './components/VoicePlayer';
import { ProgressBar } from './components/ProgressBar';
import { analyzeDocument, analyzeText, analyzeDemoMode, fetchVoiceStory } from './api/client';

// Req 10.12 — polished error messages keyed on HTTP status
function getErrorMessage(err) {
  switch (err.status) {
    case 429: return `Rate limit reached. Please wait ${err.retry_after_seconds ?? 60} seconds and try again.`;
    case 413: return 'File too large. Please upload a document under 20MB.';
    case 400: return 'Unsupported file type. Please use PDF, DOCX, TXT, PNG, JPG, or TIFF.';
    case 502: return 'AI service temporarily unavailable. Please try again in a moment.';
    case 503: return 'Backend service unavailable. Please try again.';
    default:  return 'Cannot reach the server. Check your connection.';
  }
}

export default function App() {
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [isComplete, setIsComplete] = useState(false);
  const [error, setError] = useState(null);
  const [analysisResult, setAnalysisResult] = useState(null);
  const [selectedVoice, setSelectedVoice] = useState('Aoede');
  // Req 10.13 — demo mode toggled by Ctrl+Shift+D
  const [demoMode, setDemoMode] = useState(false);

  // Req 10.13 — register keyboard shortcut
  useEffect(() => {
    const handler = (e) => {
      if (e.ctrlKey && e.shiftKey && e.key === 'D') {
        setDemoMode(true);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  function handleFileSelected(newFile) {
    setAnalysisResult(null);
    setError(null);
    setFile(newFile);
  }

  async function handleAnalyze() {
    setLoading(true);
    setIsComplete(false);
    setError(null);
    try {
      // Req 10.13 — use demo endpoint when demo mode is active
      const result = demoMode ? await analyzeDemoMode() : await analyzeDocument(file);
      setAnalysisResult(result);
      setIsComplete(true);
    } catch (err) {
      setError(getErrorMessage(err));
      setIsComplete(false);
    } finally {
      setLoading(false);
    }
  }

  // Req 10.5 — handler for sample text from FileUploader
  async function handleSampleReady(sampleData) {
    setLoading(true);
    setIsComplete(false);
    setError(null);
    setAnalysisResult(null);
    try {
      const result = await analyzeText(sampleData.text, sampleData.filename);
      setAnalysisResult(result);
      setIsComplete(true);
    } catch (err) {
      setError(getErrorMessage(err));
      setIsComplete(false);
    } finally {
      setLoading(false);
    }
  }

  function handleVoiceChange(voice) {
    setSelectedVoice(voice);
  }

  async function handleVoiceStory(story, voice) {
    try {
      const response = await fetchVoiceStory(story, voice);
      const audioBase64 = response.audio;
      const binaryStr = atob(audioBase64);
      const bytes = new Uint8Array(binaryStr.length).map((_, i) => binaryStr.charCodeAt(i));
      const blob = new Blob([bytes], { type: 'audio/wav' });
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.onended = () => URL.revokeObjectURL(url);
      audio.play();
    } catch (err) {
      console.error('Voice story error:', err);
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 py-8 px-4">
      <div className="max-w-3xl mx-auto">
        <h1 className="text-3xl font-bold text-gray-900 mb-8 text-center">
          AI Requirement Summarizer
        </h1>

        <FileUploader
          onFileSelected={handleFileSelected}
          onSubmit={handleAnalyze}
          onSampleReady={handleSampleReady}
          loading={loading}
        />

        {/* Req 10.6 — multi-step progress bar replaces plain spinner */}
        <div data-testid="loading-indicator">
          <ProgressBar isLoading={loading} isComplete={isComplete} />
        </div>

        {error && (
          <div data-testid="error-message" role="alert" className="mt-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">
            {error}
          </div>
        )}

        {analysisResult && (
          <div data-testid="results-section" className="mt-8 space-y-6">
            {/* Req 10.13 — DEMO MODE badge */}
            {demoMode && (
              <span className="bg-blue-100 text-blue-700 text-xs px-2 py-0.5 rounded-full">DEMO MODE</span>
            )}
            <ResultsTabs
              analysisResult={analysisResult}
              onVoiceStory={handleVoiceStory}
              selectedVoice={selectedVoice}
            />
            <VoicePlayer
              analysisResult={analysisResult}
              onVoiceChange={handleVoiceChange}
            />
          </div>
        )}
      </div>
    </div>
  );
}
