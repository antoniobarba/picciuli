import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './app/App';
import { createUserManager } from './auth/oidc';
import { loadConfig } from './config';
import './styles.css';

const root = createRoot(document.getElementById('root')!);

loadConfig()
  .then((config) => {
    root.render(
      <StrictMode>
        <App config={config} manager={createUserManager(config)} />
      </StrictMode>,
    );
  })
  .catch((error: unknown) => {
    root.render(
      <main className="welcome">
        <h1>Picciuli</h1>
        <p className="form-error">{error instanceof Error ? error.message : String(error)}</p>
      </main>,
    );
  });
