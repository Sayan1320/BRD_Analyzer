// Feature: react-frontend
// Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 4.8, 10.7, 10.8, 10.9

import { useState } from 'react';
import GapFlags from './GapFlags';
import { exportAsMarkdown, exportAsJSON, copyToClipboard } from '../utils/exportUtils';

const TABS = [
  { key: 'summary', label: 'Summary' },
  { key: 'stories', label: 'User Stories' },
  { key: 'criteria', label: 'Acceptance Criteria' },
  { key: 'gaps', label: 'Gap Flags' },
];

const PRIORITY_BADGE = {
  high: 'bg-red-100 text-red-800',
  medium: 'bg-yellow-100 text-yellow-800',
  low: 'bg-green-100 text-green-800',
};

function SummaryPanel({ analysis }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await copyToClipboard(analysis.executive_summary);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div data-testid="panel-summary">
      <div className="bg-white rounded-lg shadow p-4 mb-4">
        <div className="flex justify-end mb-2">
          <button
            data-testid="copy-summary-btn"
            onClick={handleCopy}
            className="text-sm px-3 py-1 rounded border border-gray-300 text-gray-600 hover:bg-gray-50 transition-colors"
          >
            {copied ? 'Copied!' : 'Copy Summary'}
          </button>
        </div>
        <p className="text-gray-800 whitespace-pre-wrap">{analysis.executive_summary}</p>
      </div>
      {(analysis.token_count != null || analysis.processing_time != null || analysis.model_name != null) && (
        <div className="bg-white rounded-lg shadow p-4 flex flex-wrap gap-4 text-sm text-gray-600">
          {analysis.token_count != null && (
            <span><span className="font-semibold">Tokens:</span> {analysis.token_count}</span>
          )}
          {analysis.processing_time != null && (
            <span><span className="font-semibold">Time:</span> {analysis.processing_time}s</span>
          )}
          {analysis.model_name != null && (
            <span><span className="font-semibold">Model:</span> {analysis.model_name}</span>
          )}
        </div>
      )}
    </div>
  );
}

function UserStoriesPanel({ userStories, onVoiceStory, selectedVoice }) {
  return (
    <div data-testid="panel-stories">
      {userStories.map((story) => (
        <div key={story.id} data-testid="story-card" className="bg-white rounded-lg shadow p-4 mb-3">
          <div className="flex justify-between items-start mb-2">
            <span
              className={`inline-block px-2 py-1 rounded text-xs font-semibold ${PRIORITY_BADGE[story.priority] ?? 'bg-gray-100 text-gray-800'}`}
            >
              {story.priority}
            </span>
            <button
              data-testid="voice-story-btn"
              onClick={() => onVoiceStory(story, selectedVoice)}
              className="text-lg hover:opacity-70 transition-opacity"
              aria-label="Listen to story"
            >
              🔊
            </button>
          </div>
          <p className="text-gray-800 mb-1">
            <span className="font-semibold">As a</span> {story.role},
          </p>
          <p className="text-gray-800 mb-1">
            <span className="font-semibold">I want</span> {story.feature},
          </p>
          <p className="text-gray-800">
            <span className="font-semibold">so that</span> {story.benefit}.
          </p>
        </div>
      ))}
    </div>
  );
}

function CriteriaPanel({ acceptanceCriteria }) {
  return (
    <div data-testid="panel-criteria">
      {acceptanceCriteria.map((criterion) => (
        <div key={criterion.id} data-testid="criteria-card" className="bg-white rounded-lg shadow p-4 mb-3">
          <p className="text-gray-800 mb-2">
            <span className="font-semibold text-blue-700">Given</span> {criterion.given}
          </p>
          <p className="text-gray-800 mb-2">
            <span className="font-semibold text-blue-700">When</span> {criterion.when}
          </p>
          <p className="text-gray-800">
            <span className="font-semibold text-blue-700">Then</span> {criterion.then}
          </p>
        </div>
      ))}
    </div>
  );
}

function GapsPanel({ gapFlags }) {
  return (
    <div data-testid="panel-gaps">
      {gapFlags && gapFlags.length > 0 ? (
        <GapFlags gapFlags={gapFlags} />
      ) : (
        <p data-testid="no-gaps-message" className="text-green-700 font-medium">
          ✅ No gaps detected
        </p>
      )}
    </div>
  );
}

export default function ResultsTabs({ analysisResult, onVoiceStory, selectedVoice }) {
  const [activeTab, setActiveTab] = useState('summary');

  const analysis = analysisResult.analysis;

  return (
    <div>
      {/* Export buttons row */}
      <div className="flex gap-2 mb-3">
        <button
          data-testid="export-md-btn"
          onClick={() => exportAsMarkdown(analysisResult, analysisResult.filename)}
          className="text-sm px-3 py-1 rounded border border-gray-300 text-gray-600 hover:bg-gray-50 transition-colors"
        >
          Export as Markdown
        </button>
        <button
          data-testid="export-json-btn"
          onClick={() => exportAsJSON(analysisResult, analysisResult.filename)}
          className="text-sm px-3 py-1 rounded border border-gray-300 text-gray-600 hover:bg-gray-50 transition-colors"
        >
          Export as JSON
        </button>
      </div>

      {/* Tab buttons */}
      <div className="flex border-b border-gray-200 mb-4">
        {TABS.map(({ key, label }) => (
          <button
            key={key}
            data-testid={`tab-${key}`}
            onClick={() => setActiveTab(key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === key
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Panels — hidden via CSS, not unmounted */}
      <div className={activeTab === 'summary' ? '' : 'hidden'}>
        <SummaryPanel analysis={analysis} />
      </div>

      <div className={activeTab === 'stories' ? '' : 'hidden'}>
        <UserStoriesPanel
          userStories={analysis.user_stories}
          onVoiceStory={onVoiceStory}
          selectedVoice={selectedVoice}
        />
      </div>

      <div className={activeTab === 'criteria' ? '' : 'hidden'}>
        <CriteriaPanel acceptanceCriteria={analysis.acceptance_criteria} />
      </div>

      <div className={activeTab === 'gaps' ? '' : 'hidden'}>
        <GapsPanel gapFlags={analysis.gap_flags} />
      </div>
    </div>
  );
}
