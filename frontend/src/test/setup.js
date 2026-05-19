import '@testing-library/jest-dom';

// jsdom in this Vitest version starts without a valid localStorage path.
// Replace it with a working in-memory implementation.
const store = {};
const localStorageMock = {
  getItem: (key) => store[key] ?? null,
  setItem: (key, value) => { store[key] = String(value); },
  removeItem: (key) => { delete store[key]; },
  clear: () => { Object.keys(store).forEach((k) => delete store[k]); },
};
Object.defineProperty(window, 'localStorage', { value: localStorageMock, writable: true });
