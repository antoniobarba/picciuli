import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { renderWithApi } from '../test/render';
import { Categories } from '../screens/Categories';

const routes = {
  'GET /api/v1/categories': [
    { id: 1, name: 'Food', symbol: 'F', parent_id: null, position: 1 },
    { id: 2, name: 'Home', symbol: 'H', parent_id: null, position: 2 },
    { id: 3, name: 'Groceries', symbol: 'G', parent_id: 1, position: 1 },
    { id: 4, name: 'Restaurants', symbol: 'R', parent_id: 1, position: 2 },
  ],
};

async function focusHandle(name: string) {
  const handle = await screen.findByRole('button', { name: `Reorder ${name}` });
  act(() => handle.focus());
  return handle;
}

async function expandFood() {
  fireEvent.click(await screen.findByText('Food'));
}

const patches = (requests: { method: string; path: string; body: unknown }[]) =>
  requests.filter((r) => r.method === 'PATCH').map(({ path, body }) => ({ path, body }));

describe('keyboard reordering', () => {
  it('moves a row one step with alt+arrows on its handle', async () => {
    const { requests } = renderWithApi(<Categories />, routes);
    const user = userEvent.setup();
    await expandFood();
    await focusHandle('Restaurants');
    await user.keyboard('{Alt>}{ArrowUp}{/Alt}');
    await waitFor(() =>
      expect(patches(requests)).toEqual([{ path: '/api/v1/categories/4', body: { position: 1 } }]),
    );
    expect(screen.getByText('Restaurants moved to position 1 of 2.')).toHaveAttribute('aria-live', 'assertive');
  });

  it('picks a row up with space, moves it among its siblings only and drops it', async () => {
    const { requests } = renderWithApi(<Categories />, routes);
    const user = userEvent.setup();
    await expandFood();
    const handle = await focusHandle('Groceries');
    await user.keyboard(' ');
    expect(handle).toHaveAttribute('aria-pressed', 'true');
    await user.keyboard('{ArrowDown}{ArrowDown}{ArrowDown}');
    expect(document.querySelector('tr.drop-after')).toHaveTextContent('Restaurants');
    await user.keyboard(' ');
    await waitFor(() =>
      expect(patches(requests)).toEqual([{ path: '/api/v1/categories/3', body: { position: 2 } }]),
    );
  });

  it('cancels with escape and does not reach the row behind the handle', async () => {
    const { requests } = renderWithApi(<Categories />, routes);
    const user = userEvent.setup();
    await focusHandle('Home');
    await user.keyboard(' {ArrowUp}');
    expect(document.querySelector('tr.drop-before')).toHaveTextContent('Food');
    await user.keyboard('{Escape}{Enter}{Escape}');
    expect(document.querySelector('tr.drop-before')).toBeNull();
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(patches(requests)).toEqual([]);
  });
});

describe('pointer reordering', () => {
  it('drags a parent with its children above another parent', async () => {
    const { requests } = renderWithApi(<Categories />, routes);
    await expandFood();
    const handle = await screen.findByRole('button', { name: 'Reorder Home' });
    // Food, Groceries, Restaurants, Home: 40px rows; Food's block spans its children.
    document.querySelectorAll('tbody tr').forEach((row, i) => {
      row.getBoundingClientRect = () => ({ top: 200 + i * 40, bottom: 240 + i * 40 }) as DOMRect;
    });
    fireEvent.pointerDown(handle, { button: 0, isPrimary: true, pointerId: 1, clientY: 340 });
    fireEvent.pointerMove(handle, { isPrimary: true, pointerId: 1, clientY: 270 });
    expect(document.querySelector('tr.drop-before, tr.drop-after')).toBeNull();
    fireEvent.pointerMove(handle, { isPrimary: true, pointerId: 1, clientY: 250 });
    expect(document.querySelector('tr.drop-before')).toHaveTextContent('Food');
    expect(document.querySelector('tr.dragging')).toHaveTextContent('Home');
    fireEvent.pointerUp(handle, { isPrimary: true, pointerId: 1, clientY: 250 });
    await waitFor(() =>
      expect(patches(requests)).toEqual([{ path: '/api/v1/categories/2', body: { position: 1 } }]),
    );
  });

  it('drags a parent above a collapsed parent', async () => {
    const { requests } = renderWithApi(<Categories />, routes);
    const handle = await screen.findByRole('button', { name: 'Reorder Home' });
    // Food, Home: 40px rows, Food's subcategories hidden.
    document.querySelectorAll('tbody tr').forEach((row, i) => {
      row.getBoundingClientRect = () => ({ top: 200 + i * 40, bottom: 240 + i * 40 }) as DOMRect;
    });
    fireEvent.pointerDown(handle, { button: 0, isPrimary: true, pointerId: 1, clientY: 260 });
    fireEvent.pointerMove(handle, { isPrimary: true, pointerId: 1, clientY: 210 });
    expect(document.querySelector('tr.drop-before')).toHaveTextContent('Food');
    fireEvent.pointerUp(handle, { isPrimary: true, pointerId: 1, clientY: 210 });
    await waitFor(() =>
      expect(patches(requests)).toEqual([{ path: '/api/v1/categories/2', body: { position: 1 } }]),
    );
  });
});
