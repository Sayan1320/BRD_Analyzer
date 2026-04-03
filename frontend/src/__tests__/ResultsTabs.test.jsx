// Feature: react-frontend, Property 5: Tab content renders one card per item

import { render, screen, fireEvent } from '@testing-library/react';
import * as fc from 'fast-check';
import ResultsTabs from '../components/ResultsTabs';

const noop = () => {};

function makeAnalysisResult({ user_stories = [], acceptance_criteria = [], gap_flags = [] } = {}) {
  return {
    analysis: {
      executive_summary: 'Test summary',
      user_stories,
      acceptance_criteria,
      gap_flags,
    },
  };
}

// Property 5: Tab content renders one card per item
// Validates: Requirements 3.4, 3.5, 3.6

test('P5 – user stories: renders one story-card per item', () => {
  fc.assert(
    fc.property(
      fc.array(
        fc.record({
          id: fc.string(),
          role: fc.string(),
          feature: fc.string(),
          benefit: fc.string(),
          priority: fc.string(),
        }),
        { minLength: 1 }
      ),
      (userStories) => {
        const { unmount } = render(
          <ResultsTabs
            analysisResult={makeAnalysisResult({ user_stories: userStories })}
            onVoiceStory={noop}
            selectedVoice="Aoede"
          />
        );

        fireEvent.click(screen.getByTestId('tab-stories'));
        const cards = screen.queryAllByTestId('story-card');
        unmount();

        return cards.length === userStories.length;
      }
    ),
    { numRuns: 100 }
  );
});

test('P5 – acceptance criteria: renders one criteria-card per item', () => {
  fc.assert(
    fc.property(
      fc.array(
        fc.record({
          id: fc.string(),
          given: fc.string(),
          when: fc.string(),
          then: fc.string(),
        }),
        { minLength: 1 }
      ),
      (acceptanceCriteria) => {
        const { unmount } = render(
          <ResultsTabs
            analysisResult={makeAnalysisResult({ acceptance_criteria: acceptanceCriteria })}
            onVoiceStory={noop}
            selectedVoice="Aoede"
          />
        );

        fireEvent.click(screen.getByTestId('tab-criteria'));
        const cards = screen.queryAllByTestId('criteria-card');
        unmount();

        return cards.length === acceptanceCriteria.length;
      }
    ),
    { numRuns: 100 }
  );
});

test('P5 – gap flags: renders one gap-flag-card per item', () => {
  fc.assert(
    fc.property(
      fc.array(
        fc.record({
          id: fc.string(),
          description: fc.string(),
          severity: fc.constantFrom('high', 'medium', 'low'),
        }),
        { minLength: 1 }
      ),
      (gapFlags) => {
        const { unmount } = render(
          <ResultsTabs
            analysisResult={makeAnalysisResult({ gap_flags: gapFlags })}
            onVoiceStory={noop}
            selectedVoice="Aoede"
          />
        );

        fireEvent.click(screen.getByTestId('tab-gaps'));
        const cards = screen.queryAllByTestId('gap-flag-card');
        unmount();

        return cards.length === gapFlags.length;
      }
    ),
    { numRuns: 100 }
  );
});

// Unit tests 9.6–9.8

describe('ResultsTabs — unit tests', () => {
  // 9.6: renders exactly four tab buttons (Requirements: 3.1)
  it('9.6: renders exactly four tab buttons', () => {
    const { getAllByTestId } = render(
      <ResultsTabs
        analysisResult={makeAnalysisResult()}
        onVoiceStory={noop}
        selectedVoice="Aoede"
      />
    );
    // tab-summary, tab-stories, tab-criteria, tab-gaps
    const tabs = getAllByTestId(/^tab-/);
    expect(tabs).toHaveLength(4);
  });

  // 9.7: clicking a tab shows its panel and applies active style (Requirements: 3.2)
  it('9.7: clicking a tab shows its panel and applies active style', () => {
    const { getByTestId } = render(
      <ResultsTabs
        analysisResult={makeAnalysisResult({
          user_stories: [{ id: '1', role: 'user', feature: 'feat', benefit: 'ben', priority: 'high' }],
        })}
        onVoiceStory={noop}
        selectedVoice="Aoede"
      />
    );
    const storiesTab = getByTestId('tab-stories');
    fireEvent.click(storiesTab);
    // Panel should not be hidden
    const panel = getByTestId('panel-stories');
    expect(panel.parentElement.className).not.toContain('hidden');
    // Active tab should have active class (border-blue-600)
    expect(storiesTab.className).toContain('border-blue-600');
  });

  // 9.8: empty gap_flags array shows "✅ No gaps detected" (Requirements: 3.7)
  it('9.8: empty gap_flags array shows "✅ No gaps detected"', () => {
    const { getByTestId } = render(
      <ResultsTabs
        analysisResult={makeAnalysisResult({ gap_flags: [] })}
        onVoiceStory={noop}
        selectedVoice="Aoede"
      />
    );
    fireEvent.click(getByTestId('tab-gaps'));
    expect(getByTestId('no-gaps-message')).toBeTruthy();
  });
});
