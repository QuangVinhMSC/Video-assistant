import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ApiKeyGate from '../components/ApiKeyGate';

// Test 7
test('Continue button is disabled when input is empty', () => {
  render(<ApiKeyGate onSave={() => {}} />);
  expect(screen.getByRole('button', { name: /continue/i })).toBeDisabled();
});

// Test 8
test('saves key to localStorage and calls onSave when submitted', async () => {
  const onSave = vi.fn();
  render(<ApiKeyGate onSave={onSave} />);
  await userEvent.type(screen.getByPlaceholderText(/enter your api key/i), 'my-secret-key');
  await userEvent.click(screen.getByRole('button', { name: /continue/i }));
  expect(localStorage.getItem('api_key')).toBe('my-secret-key');
  expect(onSave).toHaveBeenCalledWith('my-secret-key');
});
