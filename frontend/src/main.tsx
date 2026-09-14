import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './app/App';
import './styles.css';

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('未找到应用根节点。');
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  void navigator.serviceWorker
    .register(`${import.meta.env.BASE_URL}service-worker.js`)
    .catch(() => {
      // The application remains usable when offline shell caching is unavailable.
    });
}
