export default function ProgressBar({ percent }) {
  return (
    <div className="w-full bg-gray-200 rounded-full h-2 overflow-hidden">
      <div
        className="h-2 bg-violet-600 rounded-full transition-all duration-700 ease-out"
        style={{ width: `${percent}%` }}
      />
    </div>
  );
}
