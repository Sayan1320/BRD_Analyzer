// Feature: react-frontend, Property 1: File display format
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, fireEvent, cleanup } from '@testing-library/react';
import * as fc from 'fast-check';
import FileUploader from '../components/FileUploader';

afterEach(() => {
  cleanup();
});

describe('FileUploader - Property 1: File display format', () => {
  /**
   * Property 1: File display format
   * Validates: Requirements 1.4
   *
   * For any File object with a non-empty name and a positive size,
   * the display string produced by the FileUploader SHALL contain the filename
   * and a human-readable size representation (e.g. "1.4 MB" or "KB").
   */
  it('P1: displays filename and human-readable size for any valid file', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 1 }),
        fc.integer({ min: 1, max: 20971520 }),
        (filename, size) => {
          const mockFile = {
            name: filename + '.pdf',
            size: size,
            type: 'application/pdf',
          };

          const { getByTestId, unmount } = render(
            <FileUploader
              onFileSelected={vi.fn()}
              onSubmit={vi.fn()}
              loading={false}
            />
          );

          const input = getByTestId('file-input');
          fireEvent.change(input, { target: { files: [mockFile] } });

          const fileInfo = getByTestId('file-info');
          const text = fileInfo.textContent;

          unmount();

          expect(text).toContain(filename + '.pdf');
          expect(text.includes('KB') || text.includes('MB')).toBe(true);
        }
      ),
      { numRuns: 100 }
    );
  });
});

// Feature: react-frontend, Property 2: File size validation rejects oversized files
describe('FileUploader - Property 2: File size validation rejects oversized files', () => {
  /**
   * Property 2: File size validation rejects oversized files
   * Validates: Requirements 1.7
   *
   * For any File object whose size exceeds 20 MB (20 × 1024 × 1024 bytes),
   * the FileUploader SHALL set a non-empty validation error and SHALL NOT
   * enable the "Analyze Document" button.
   */
  it('P2: shows validation error and disables button for any file > 20 MB', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 20971521, max: 100000000 }),
        (size) => {
          const mockFile = {
            name: 'oversized.pdf',
            size: size,
            type: 'application/pdf',
          };

          const { getByTestId, unmount } = render(
            <FileUploader
              onFileSelected={vi.fn()}
              onSubmit={vi.fn()}
              loading={false}
            />
          );

          const input = getByTestId('file-input');
          fireEvent.change(input, { target: { files: [mockFile] } });

          const validationError = getByTestId('validation-error');
          expect(validationError).toBeTruthy();
          expect(validationError.textContent.length).toBeGreaterThan(0);

          const analyzeBtn = getByTestId('analyze-btn');
          expect(analyzeBtn).toBeDisabled();

          unmount();
        }
      ),
      { numRuns: 100 }
    );
  });
});

// Feature: react-frontend, Property 3: File type validation rejects unsupported extensions
describe('FileUploader - Property 3: File type validation rejects unsupported extensions', () => {
  /**
   * Property 3: File type validation rejects unsupported extensions
   * Validates: Requirements 1.8
   *
   * For any filename whose extension is not in {.pdf, .docx, .txt, .png, .jpg, .tiff},
   * the FileUploader SHALL set a non-empty validation error and SHALL NOT
   * enable the "Analyze Document" button.
   */
  it('P3: shows validation error and disables button for any unsupported file extension', () => {
    const SUPPORTED_EXTS = ['.pdf', '.docx', '.txt', '.png', '.jpg', '.tiff'];

    fc.assert(
      fc.property(
        fc.string({ minLength: 1 }).filter(name => {
          const idx = name.lastIndexOf('.');
          if (idx === -1) return true; // no extension = unsupported
          const ext = name.slice(idx).toLowerCase();
          return !SUPPORTED_EXTS.includes(ext);
        }),
        (filename) => {
          const mockFile = {
            name: filename,
            size: 1024, // valid size < 20 MB
            type: 'application/octet-stream',
          };

          const { getByTestId, unmount } = render(
            <FileUploader
              onFileSelected={vi.fn()}
              onSubmit={vi.fn()}
              loading={false}
            />
          );

          const input = getByTestId('file-input');
          fireEvent.change(input, { target: { files: [mockFile] } });

          const validationError = getByTestId('validation-error');
          expect(validationError).toBeTruthy();
          expect(validationError.textContent.length).toBeGreaterThan(0);

          const analyzeBtn = getByTestId('analyze-btn');
          expect(analyzeBtn).toBeDisabled();

          unmount();
        }
      ),
      { numRuns: 100 }
    );
  });
});

// Unit tests 9.1–9.5

describe('FileUploader — unit tests', () => {
  // 9.1: renders drop zone with dashed border (Requirements: 1.1)
  it('9.1: renders drop zone with dashed border', () => {
    const { getByTestId } = render(
      <FileUploader onFileSelected={vi.fn()} onSubmit={vi.fn()} loading={false} />
    );
    const dropZone = getByTestId('drop-zone');
    expect(dropZone).toBeTruthy();
    expect(dropZone.className).toContain('border-dashed');
  });

  // 9.2: displays filename and size after valid file selection (Requirements: 1.4)
  it('9.2: displays filename and size after valid file selection', () => {
    const { getByTestId } = render(
      <FileUploader onFileSelected={vi.fn()} onSubmit={vi.fn()} loading={false} />
    );
    const input = getByTestId('file-input');
    const file = { name: 'report.pdf', size: 1024 * 1024, type: 'application/pdf' };
    fireEvent.change(input, { target: { files: [file] } });
    const fileInfo = getByTestId('file-info');
    expect(fileInfo.textContent).toContain('report.pdf');
    expect(fileInfo.textContent.includes('KB') || fileInfo.textContent.includes('MB')).toBe(true);
  });

  // 9.3: shows error and disables button for file > 20 MB (Requirements: 1.7)
  it('9.3: shows error and disables button for file > 20 MB', () => {
    const { getByTestId } = render(
      <FileUploader onFileSelected={vi.fn()} onSubmit={vi.fn()} loading={false} />
    );
    const input = getByTestId('file-input');
    const file = { name: 'big.pdf', size: 20971521, type: 'application/pdf' };
    fireEvent.change(input, { target: { files: [file] } });
    expect(getByTestId('validation-error')).toBeTruthy();
    expect(getByTestId('analyze-btn')).toBeDisabled();
  });

  // 9.4: shows error and disables button for unsupported extension (Requirements: 1.8)
  it('9.4: shows error and disables button for unsupported extension', () => {
    const { getByTestId } = render(
      <FileUploader onFileSelected={vi.fn()} onSubmit={vi.fn()} loading={false} />
    );
    const input = getByTestId('file-input');
    const file = { name: 'test.xyz', size: 1024, type: 'application/octet-stream' };
    fireEvent.change(input, { target: { files: [file] } });
    expect(getByTestId('validation-error')).toBeTruthy();
    expect(getByTestId('analyze-btn')).toBeDisabled();
  });

  // 9.5: button is disabled while loading prop is true (Requirements: 2.2)
  it('9.5: button is disabled while loading prop is true', () => {
    const { getByTestId } = render(
      <FileUploader onFileSelected={vi.fn()} onSubmit={vi.fn()} loading={true} />
    );
    // Select a valid file first so the only reason for disable is loading
    const input = getByTestId('file-input');
    const file = { name: 'doc.pdf', size: 1024, type: 'application/pdf' };
    fireEvent.change(input, { target: { files: [file] } });
    expect(getByTestId('analyze-btn')).toBeDisabled();
  });
});
