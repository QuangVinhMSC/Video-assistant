import { render, screen } from '@testing-library/react';
import MessageBubble from '../components/MessageBubble';

// Test 9
test('user message renders on the right with the question text', () => {
  const { container } = render(<MessageBubble role="user" content="What is breathing control?" />);
  expect(screen.getByText('What is breathing control?')).toBeInTheDocument();
  expect(container.firstChild).toHaveClass('flex', 'justify-end');
});

// Test 10
test('assistant structured response renders answer, video points, and timestamps', async () => {
  const content = {
    answer: 'Breathing control is the foundation of vocal training.',
    based_on_video: ['The instructor demonstrates diaphragm breathing at 02:05'],
    expert_explanation: ['Proper breath support prevents vocal strain'],
    relevant_timestamps: [{ start: 125, end: 180 }],
    search_used: false,
  };
  render(<MessageBubble role="assistant" content={content} />);

  expect(await screen.findByText(/breathing control is the foundation/i)).toBeInTheDocument();
  expect(screen.getByText(/demonstrates diaphragm breathing/i)).toBeInTheDocument();
  expect(screen.getByText(/prevents vocal strain/i)).toBeInTheDocument();
  expect(screen.getByText('02:05 → 03:00')).toBeInTheDocument();
});
