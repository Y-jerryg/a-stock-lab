import { render, screen } from '@testing-library/react';

import { App } from './App';

describe('application navigation', () => {
  it('renders the Tail Radar empty state without fake results', async () => {
    window.location.hash = '#/tail-radar';
    render(<App />);

    expect(
      await screen.findByRole('heading', { name: 'Tail Radar', level: 1 }),
    ).toBeInTheDocument();
    expect(screen.getByText('No research run has been produced')).toBeInTheDocument();
    expect(screen.queryByText(/stock price/i)).not.toBeInTheDocument();
  });
});
