import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
// Tokens and base styles must be emitted before any component stylesheet so
// component rules win on equal specificity.
import './styles/base.css';
import App from './App';

const container = document.getElementById('root');
if (!container) throw new Error('Root container missing');

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>
);
