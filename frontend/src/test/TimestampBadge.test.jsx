import { render, screen } from '@testing-library/react';
import TimestampBadge from '../components/TimestampBadge';

// Test 1
test('formats seconds into MM:SS → MM:SS', () => {
  render(<TimestampBadge start={125} end={180} />);
  expect(screen.getByText('02:05 → 03:00')).toBeInTheDocument();
});

// Test 2
test('pads single-digit minutes and seconds', () => {
  render(<TimestampBadge start={0} end={9} />);
  expect(screen.getByText('00:00 → 00:09')).toBeInTheDocument();
});
