// Feature: react-frontend
// Requirements: 3.6

const BADGE_CLASSES = {
  high: 'bg-red-100 text-red-800',
  medium: 'bg-yellow-100 text-yellow-800',
  low: 'bg-green-100 text-green-800',
};

export default function GapFlags({ gapFlags }) {
  if (!gapFlags || gapFlags.length === 0) {
    return null;
  }

  return (
    <>
      {gapFlags.map((flag) => (
        <div
          key={flag.id}
          data-testid="gap-flag-card"
          className="bg-white rounded-lg shadow p-4 mb-3"
        >
          <p className="text-gray-800 mb-2">{flag.description}</p>
          <span
            data-testid="severity-badge"
            className={`inline-block px-2 py-1 rounded text-xs font-semibold ${BADGE_CLASSES[flag.severity] ?? 'bg-gray-100 text-gray-800'}`}
          >
            {flag.severity}
          </span>
        </div>
      ))}
    </>
  );
}
