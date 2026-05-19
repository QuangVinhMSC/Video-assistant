import { render, screen } from '@testing-library/react';
import StatusTimeline from '../components/StatusTimeline';

// Test 5
test('shows all 7 pipeline steps', () => {
  render(<StatusTimeline currentStatus="uploaded" />);
  expect(screen.getByText('Uploaded')).toBeInTheDocument();
  expect(screen.getByText('Extracting audio')).toBeInTheDocument();
  expect(screen.getByText('Transcribing')).toBeInTheDocument();
  expect(screen.getByText('Summarizing')).toBeInTheDocument();
  expect(screen.getByText('Chunking')).toBeInTheDocument();
  expect(screen.getByText('Embedding')).toBeInTheDocument();
  expect(screen.getByText('Ready')).toBeInTheDocument();
});

// Test 6
test('active step has violet text, prior steps have normal text', () => {
  render(<StatusTimeline currentStatus="transcribing" />);
  expect(screen.getByText('Transcribing')).toHaveClass('text-violet-600');
  expect(screen.getByText('Uploaded')).toHaveClass('text-gray-700');
  expect(screen.getByText('Summarizing')).toHaveClass('text-gray-400');
});
