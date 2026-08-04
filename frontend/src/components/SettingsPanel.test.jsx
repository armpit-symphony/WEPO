import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { vi } from 'vitest';

vi.mock('../contexts/WalletContext', () => ({
  useWallet: () => ({ changePassword: vi.fn() }),
}));

import SettingsPanel from './SettingsPanel';

test('exposes the implemented local-vault password rotation control', () => {
  const markup = renderToStaticMarkup(<SettingsPanel onClose={() => {}} />);

  expect(markup).toContain('Change Local Wallet Password');
  expect(markup).not.toContain('Password Change Not Yet Available');
  expect(markup).not.toContain('disabled=""');
  expect(markup).toContain('atomically re-encrypts the complete local vault');
});
