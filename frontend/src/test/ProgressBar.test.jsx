import { render, container } from '@testing-library/react';
import ProgressBar from '../components/ProgressBar';

// Test 3
test('fill width matches the percent prop', () => {
  const { container } = render(<ProgressBar percent={65} />);
  const fill = container.querySelector('.bg-violet-600');
  expect(fill).toHaveStyle({ width: '65%' });
});

// Test 4
test('renders 0% without error', () => {
  const { container } = render(<ProgressBar percent={0} />);
  const fill = container.querySelector('.bg-violet-600');
  expect(fill).toHaveStyle({ width: '0%' });
});
