import { useState, useRef } from 'react';
import { fetchSampleText } from '../api/client';

const MAX_SIZE_BYTES = 20 * 1024 * 1024; // 20 MB
const SUPPORTED_EXTS = ['.pdf', '.docx', '.txt', '.png', '.jpg', '.tiff'];

function formatSize(bytes) {
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function getExtension(filename) {
  const idx = filename.lastIndexOf('.');
  if (idx === -1) return '';
  return filename.slice(idx).toLowerCase();
}

function validateFile(file) {
  const ext = getExtension(file.name);
  if (!SUPPORTED_EXTS.includes(ext)) {
    return `Unsupported file type. Supported formats: PDF, DOCX, TXT, PNG, JPG, TIFF`;
  }
  if (file.size > MAX_SIZE_BYTES) {
    return `File exceeds the 20 MB limit.`;
  }
  return null;
}

export default function FileUploader({ onFileSelected, onSubmit, loading, onSampleReady }) {
  const [dragOver, setDragOver] = useState(false);
  const [file, setFile] = useState(null);
  const [validationError, setValidationError] = useState(null);
  const [sampleLoading, setSampleLoading] = useState(false);
  const inputRef = useRef(null);

  async function handleSampleBRD() {
    setSampleLoading(true);
    try {
      const result = await fetchSampleText();
      onSampleReady(result);
    } catch (_) {
      // minimal error handling
    } finally {
      setSampleLoading(false);
    }
  }

  function handleFile(selected) {
    const error = validateFile(selected);
    setValidationError(error);
    if (error) {
      setFile(null);
    } else {
      setFile(selected);
      onFileSelected(selected);
    }
  }

  function handleDragOver(e) {
    e.preventDefault();
    setDragOver(true);
  }

  function handleDragLeave() {
    setDragOver(false);
  }

  function handleDrop(e) {
    e.preventDefault();
    setDragOver(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped) handleFile(dropped);
  }

  function handleClick() {
    inputRef.current?.click();
  }

  function handleInputChange(e) {
    const selected = e.target.files[0];
    if (selected) handleFile(selected);
  }

  const isDisabled = loading || !!validationError || !file;

  return (
    <div className="w-full max-w-lg mx-auto">
      <div
        data-testid="drop-zone"
        onClick={handleClick}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
          dragOver
            ? 'border-blue-500 bg-blue-50'
            : 'border-gray-300 hover:border-gray-400'
        }`}
      >
        <input
          ref={inputRef}
          data-testid="file-input"
          type="file"
          accept=".pdf,.docx,.txt,.png,.jpg,.tiff"
          className="hidden"
          onChange={handleInputChange}
        />

        {file && !validationError ? (
          <p data-testid="file-info" className="text-sm text-gray-700 font-medium">
            {file.name} — {formatSize(file.size)}
          </p>
        ) : (
          <p className="text-gray-500 text-sm">
            Drag &amp; drop a file here, or click to select
          </p>
        )}

        {validationError && (
          <p data-testid="validation-error" className="mt-2 text-sm text-red-600">
            {validationError}
          </p>
        )}

        <p className="mt-3 text-xs text-gray-400">
          Supported formats: PDF, DOCX, TXT, PNG, JPG, TIFF
        </p>
      </div>

      <button
        data-testid="analyze-btn"
        onClick={onSubmit}
        disabled={isDisabled}
        className={`mt-4 w-full py-2 px-4 rounded-lg font-semibold text-white transition-colors ${
          isDisabled
            ? 'bg-gray-300 cursor-not-allowed'
            : 'bg-blue-600 hover:bg-blue-700'
        }`}
      >
        {loading ? 'Analyzing...' : 'Analyze Document'}
      </button>

      <button
        data-testid="sample-btn"
        onClick={handleSampleBRD}
        disabled={loading || sampleLoading}
        className={`mt-2 w-full py-2 px-4 rounded-lg font-semibold transition-colors border border-blue-600 text-blue-600 hover:bg-blue-50 ${
          (loading || sampleLoading) ? 'opacity-50 cursor-not-allowed' : ''
        }`}
      >
        {sampleLoading ? 'Loading sample...' : 'Try with Sample BRD'}
      </button>
    </div>
  );
}
