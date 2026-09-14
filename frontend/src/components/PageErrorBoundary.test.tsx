import { lazy, Suspense } from 'react';
import { render, screen } from '@testing-library/react';
import { vi } from 'vitest';

import { PageErrorBoundary } from './PageErrorBoundary';

it('keeps a recovery action visible when an obsolete page chunk cannot load', async () => {
  const log = vi.spyOn(console, 'error').mockImplementation(() => undefined);
  const BrokenPage = lazy(() =>
    Promise.reject(new TypeError('Failed to fetch dynamically imported module')),
  );
  try {
    render(
      <PageErrorBoundary>
        <Suspense fallback="加载中">
          <BrokenPage />
        </Suspense>
      </PageErrorBoundary>,
    );
    expect(await screen.findByRole('alert')).toHaveTextContent('页面加载失败');
    expect(screen.getByRole('button', { name: '刷新页面' })).toBeEnabled();
  } finally {
    log.mockRestore();
  }
});
