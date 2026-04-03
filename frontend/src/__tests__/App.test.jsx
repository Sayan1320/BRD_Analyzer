import * as fc from 'fast-check';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { vi } from 'vitest';
import App from '../App.jsx';
import { analyzeDocument } from '../api/client.js';

vi.mock('../api/client.js', () => ({
  analyzeDocument: vi.fn(),
  fetchVoiceSummary: vi.fn(),
  fetchVoiceStory: vi.fn(),
}));

// Feature: react-frontend, Property 4: Error handling restores UI state
// Validates: Requirements 2.4, 2.5
describe('App', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('P4: error handling restores UI state after failed analysis', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: 400, max: 599 }),
        async (statusCode) => {
          const err = new Error('Request failed');
          err.status = statusCode;
          analyzeDocument.mockRejectedValueOnce(err);

          const { unmount } = render(<App />);

          // Select a valid file
          const fileInput = screen.getByTestId('file-input');
          const file = new File(['content'], 'test.pdf', { type: 'application/pdf' });
          fireEvent.change(fileInput, { target: { files: [file] } });

          // Trigger analysis
          const analyzeBtn = screen.getByTestId('analyze-btn');
          fireEvent.click(analyzeBtn);

          // Wait for the error state to settle
          await waitFor(() => {
            expect(screen.queryByTestId('loading-indicator')).not.toBeInTheDocument();
          });

          // Error message should be visible and non-empty
          const errorEl = screen.getByTestId('error-message');
          expect(errorEl.textContent.trim().length).toBeGreaterThan(0);

          unmount();
        }
      ),
      { numRuns: 100 }
    );
  });
});

// Unit tests 9.12–9.13

const validResult = {
  session_id: 'abc',
  filename: 'test.pdf',
  char_count: 100,
  page_count: 1,
  analysis: {
    executive_summary: 'Summary',
    user_stories: [],
    acceptance_criteria: [],
    gap_flags: [],
  },
};

describe('App — unit tests', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  // 9.12: clears previous analysisResult when a new file is selected (Requirements: 2.6)
  it('9.12: clears previous analysisResult when a new file is selected', async () => {
    analyzeDocument.mockResolvedValueOnce(validResult);

    render(<App />);

    // Select file and analyze
    const fileInput = screen.getByTestId('file-input');
    fireEvent.change(fileInput, {
      target: { files: [new File(['content'], 'test.pdf', { type: 'application/pdf' })] },
    });
    fireEvent.click(screen.getByTestId('analyze-btn'));

    // Wait for results to appear
    await waitFor(() => expect(screen.getByTestId('results-section')).toBeTruthy());

    // Select a new file — results should disappear
    fireEvent.change(fileInput, {
      target: { files: [new File(['content2'], 'new.pdf', { type: 'application/pdf' })] },
    });

    expect(screen.queryByTestId('results-section')).not.toBeInTheDocument();
  });

  // 9.13: shows loading indicator and disables button during analysis (Requirements: 2.2)
  it('9.13: shows loading indicator and disables button during analysis', async () => {
    // Never-resolving promise
    analyzeDocument.mockReturnValueOnce(new Promise(() => {}));

    render(<App />);

    const fileInput = screen.getByTestId('file-input');
    fireEvent.change(fileInput, {
      target: { files: [new File(['content'], 'test.pdf', { type: 'application/pdf' })] },
    });
    fireEvent.click(screen.getByTestId('analyze-btn'));

    await waitFor(() => expect(screen.getByTestId('loading-indicator')).toBeTruthy());
    expect(screen.getByTestId('analyze-btn')).toBeDisabled();
  });
});
