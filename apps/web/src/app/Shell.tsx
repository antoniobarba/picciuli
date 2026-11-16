import * as Menu from '@radix-ui/react-dropdown-menu';
import { Suspense, useEffect, useMemo, useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router';
import { useRegisterSW } from 'virtual:pwa-register/react';
import { useAuth } from '../auth/AuthProvider';
import { displayName } from '../auth/oidc';
import { useNotify } from '../components/feedback';
import { icons } from '../components/icons';
import { Modal } from '../components/Modal';
import { Loading } from '../components/ui';
import { useHotkeys } from '../lib/useHotkeys';
import { CommandPalette, type Command } from './CommandPalette';
import { useEditors } from './editors';
import { HelpDialog } from './HelpDialog';
import { useLivePrices } from './live';

const SCREENS = [
  { to: '/', label: 'Overview', key: '1', icon: icons.overview, mobile: true },
  { to: '/accounts', label: 'Accounts', key: '2', icon: icons.accounts, mobile: true },
  { to: '/categories', label: 'Categories', key: '3', icon: icons.categories, mobile: false },
  { to: '/periods', label: 'Periods', key: '4', icon: icons.periods, mobile: false },
  { to: '/budgets', label: 'Budgets', key: '5', icon: icons.budgets, mobile: true },
  { to: '/investments', label: 'Investments', key: '6', icon: icons.investments, mobile: true },
  { to: '/reports', label: 'Reports', key: '7', icon: icons.reports, mobile: false },
] as const;

interface InstallPrompt extends Event {
  prompt: () => Promise<void>;
}

function useInstallPrompt(): (() => void) | null {
  const [prompt, setPrompt] = useState<InstallPrompt | null>(null);
  useEffect(() => {
    const capture = (event: Event) => {
      event.preventDefault();
      setPrompt(event as InstallPrompt);
    };
    const installed = () => setPrompt(null);
    window.addEventListener('beforeinstallprompt', capture);
    window.addEventListener('appinstalled', installed);
    return () => {
      window.removeEventListener('beforeinstallprompt', capture);
      window.removeEventListener('appinstalled', installed);
    };
  }, []);
  return prompt
    ? () => {
        void prompt.prompt();
        setPrompt(null);
      }
    : null;
}

function OfflineBanner() {
  const [online, setOnline] = useState(() => navigator.onLine);
  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    window.addEventListener('online', update);
    window.addEventListener('offline', update);
    return () => {
      window.removeEventListener('online', update);
      window.removeEventListener('offline', update);
    };
  }, []);
  if (online) return null;
  return (
    <div className="update-banner offline" role="status">
      You are offline: the data shown may be out of date and changes cannot be saved.
    </div>
  );
}

function UpdateBanner() {
  const {
    needRefresh: [needRefresh, setNeedRefresh],
    updateServiceWorker,
  } = useRegisterSW({
    onRegisteredSW(_url, registration) {
      // Look for a new version every hour while the app stays open.
      if (registration) window.setInterval(() => void registration.update(), 60 * 60 * 1000);
    },
  });
  if (!needRefresh) return null;
  return (
    <div className="update-banner" role="status">
      A new version of Picciuli is available.
      <button type="button" className="button small primary" onClick={() => void updateServiceWorker(true)}>
        Reload
      </button>
      <button type="button" className="button small" onClick={() => setNeedRefresh(false)}>
        Later
      </button>
    </div>
  );
}

export function Shell() {
  const navigate = useNavigate();
  const auth = useAuth();
  const editors = useEditors();
  const live = useLivePrices();
  const notify = useNotify();
  const install = useInstallPrompt();
  const [help, setHelp] = useState(false);
  const [palette, setPalette] = useState(false);
  const [more, setMore] = useState(false);

  const toggleLive = () => {
    live.setLive(!live.live);
    notify(`Live prices ${live.live ? 'off' : 'on (every 60 s)'}`, { title: 'Prices' });
  };

  useHotkeys({
    ...Object.fromEntries(SCREENS.map((screen) => [screen.key, () => navigate(screen.to)])),
    s: () => navigate('/settings'),
    '?': () => setHelp(true),
    l: toggleLive,
    'ctrl+k': () => setPalette((open) => !open),
  });

  const commands = useMemo<Command[]>(
    () => [
      { id: 'new', label: 'New transaction', hint: 'n', run: () => editors.newTransaction() },
      ...SCREENS.map((screen) => ({
        id: screen.to,
        label: `Go to ${screen.label}`,
        hint: screen.key,
        run: () => navigate(screen.to),
      })),
      { id: 'settings', label: 'Go to Settings', hint: 's', run: () => navigate('/settings') },
      { id: 'refresh', label: 'Refresh prices', run: () => void live.refresh() },
      { id: 'live', label: live.live ? 'Live prices off' : 'Live prices on', hint: 'l', run: toggleLive },
      { id: 'help', label: 'Keyboard shortcuts', hint: '?', run: () => setHelp(true) },
      ...(install ? [{ id: 'install', label: 'Install the app', run: install }] : []),
      { id: 'signout', label: 'Sign out', run: () => void auth.signOut() },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [editors, navigate, live.live, install, auth.signOut],
  );

  const closeMore = () => setMore(false);

  return (
    <div className="shell">
      <header className="topbar">
        <NavLink to="/" className="brand" aria-label="Picciuli, overview">
          <img src="/logo.svg" alt="" width="28" height="28" />
          <span>Picciuli</span>
        </NavLink>
        <nav className="tabs" aria-label="Screens">
          {SCREENS.map((screen) => (
            <NavLink key={screen.to} to={screen.to} end={screen.to === '/'} className="tab" title={`${screen.label} (${screen.key})`}>
              {screen.label}
            </NavLink>
          ))}
        </nav>
        <div className="topbar-actions">
          {live.live ? (
            <span className="live-badge" title="Prices refresh every minute">
              ● Live
            </span>
          ) : null}
          <button type="button" className="icon-button hide-mobile" onClick={() => setPalette(true)} title="Commands (ctrl+k)" aria-label="Commands">
            ⌘
          </button>
          <Menu.Root modal={false}>
            <Menu.Trigger className="avatar" aria-label="Account menu">
              {displayName(auth.user).slice(0, 1).toUpperCase()}
            </Menu.Trigger>
            <Menu.Portal>
              <Menu.Content className="menu" align="end" sideOffset={6}>
                <Menu.Label className="menu-label">{displayName(auth.user)}</Menu.Label>
                <Menu.Item className="menu-item" onSelect={() => navigate('/settings')}>
                  Settings <kbd>s</kbd>
                </Menu.Item>
                <Menu.Item className="menu-item" onSelect={() => setHelp(true)}>
                  Keyboard shortcuts <kbd>?</kbd>
                </Menu.Item>
                {install ? (
                  <Menu.Item className="menu-item" onSelect={install}>
                    Install the app
                  </Menu.Item>
                ) : null}
                <Menu.Separator className="menu-separator" />
                <Menu.Item className="menu-item" onSelect={() => void auth.signOut()}>
                  Sign out
                </Menu.Item>
              </Menu.Content>
            </Menu.Portal>
          </Menu.Root>
        </div>
      </header>

      <UpdateBanner />
      <OfflineBanner />

      <main className="main" id="main">
        <Suspense fallback={<Loading />}>
          <Outlet />
        </Suspense>
      </main>

      <nav className="bottom-nav" aria-label="Screens">
        {SCREENS.filter((screen) => screen.mobile).map((screen) => (
          <NavLink key={screen.to} to={screen.to} end={screen.to === '/'}>
            {screen.icon}
            <span>{screen.label}</span>
          </NavLink>
        ))}
        <button type="button" onClick={() => setMore(true)} className={more ? 'active' : ''}>
          {icons.more}
          <span>More</span>
        </button>
      </nav>

      <Modal open={more} onClose={() => setMore(false)} title="More">
        <ul className="pick-list more-list" onClick={closeMore}>
          <li>
            <NavLink to="/categories">
              {icons.categories} Categories
            </NavLink>
          </li>
          <li>
            <NavLink to="/periods">
              {icons.periods} Periods
            </NavLink>
          </li>
          <li>
            <NavLink to="/reports">
              {icons.reports} Reports
            </NavLink>
          </li>
          <li>
            <NavLink to="/settings">
              {icons.settings} Settings
            </NavLink>
          </li>
          <li>
            <button type="button" onClick={toggleLive}>
              {icons.investments} Live prices: {live.live ? 'on' : 'off'}
            </button>
          </li>
          {install ? (
            <li>
              <button type="button" onClick={install}>
                {icons.install} Install the app
              </button>
            </li>
          ) : null}
          <li>
            <button type="button" onClick={() => void auth.signOut()}>
              {icons.signOut} Sign out
            </button>
          </li>
        </ul>
      </Modal>

      <HelpDialog open={help} onClose={() => setHelp(false)} />
      <CommandPalette open={palette} onClose={() => setPalette(false)} commands={commands} />
    </div>
  );
}
