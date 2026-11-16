import { useMemo, useState } from 'react';
import { unwrap, type ApiClient } from '../api/client';
import { useApi } from '../api/context';
import { useApiMutation, useCategories, useOptimisticMove } from '../api/queries';
import type { Category } from '../api/types';
import { useNotify } from '../components/feedback';
import { errorMessage, FormDialog, SelectField, TextField } from '../components/forms';
import { DragHandle, useSortable } from '../components/SortableList';
import { CategoryTransactions } from '../components/TransactionsModal';
import { Empty, Loading, onEnter, PageHeader, RowMenu } from '../components/ui';
import { byId, categoryLabel, categoryTree } from '../lib/format';
import { NONE_ID, optionalText } from '../lib/forms';
import { useHotkeys } from '../lib/useHotkeys';

type Dialog =
  | { kind: 'transactions'; category: Category }
  | { kind: 'edit'; category: Category | null; parentId: number | null }
  | { kind: 'delete'; category: Category; inUse: boolean }
  | null;

async function categoryInUse(api: ApiClient, id: number): Promise<boolean> {
  const found = await unwrap(api.GET('/api/v1/transactions', { params: { query: { category_id: id, limit: 1 } } }));
  return found.length > 0;
}

export function Categories() {
  const api = useApi();
  const notify = useNotify();
  const categories = useCategories();
  const tree = useMemo(() => categoryTree(categories.data ?? []), [categories.data]);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [expanded, setExpanded] = useState<ReadonlySet<number>>(() => new Set());
  const parentIds = useMemo(() => new Set(tree.flatMap((c) => (c.parent_id === null ? [] : [c.parent_id]))), [tree]);
  // Subcategories show only under an expanded parent.
  const visible = useMemo(
    () => tree.filter((c) => c.parent_id === null || expanded.has(c.parent_id)),
    [tree, expanded],
  );
  const selected = visible.find((c) => c.id === selectedId) ?? null;
  const toggle = (id: number) =>
    setExpanded((current) => {
      const next = new Set(current);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  const expand = (id: number) => setExpanded((current) => (current.has(id) ? current : new Set(current).add(id)));

  const move = useOptimisticMove<Category>(
    ['categories'],
    (client, { id, position }) =>
      unwrap(
        client.PATCH('/api/v1/categories/{category_id}', { params: { path: { category_id: id } }, body: { position } }),
      ),
    (a, b) => a.parent_id === b.parent_id,
  );

  // Categories reorder among the siblings under the same parent; a parent moves with its children.
  const siblingsOf = (category: Category) => tree.filter((c) => c.parent_id === category.parent_id);
  const moveCategory = async (category: Category, index: number) => {
    const target = siblingsOf(category)[index];
    if (!target || target.id === category.id) return;
    try {
      await move.mutateAsync({ id: category.id, position: index + 1 });
    } catch (error) {
      notify(errorMessage(error), { title: 'Cannot do that', kind: 'error' });
    }
  };
  const step = (category: Category, by: number) =>
    void moveCategory(category, siblingsOf(category).indexOf(category) + by);
  const sortable = useSortable<Category>({
    getId: (category) => category.id,
    siblingsOf,
    extentOf: (category) => [category, ...visible.filter((c) => c.parent_id === category.id)],
    label: (category) => category.name,
    onMove: (category, index) => void moveCategory(category, index),
  });

  const askDelete = async (category: Category) => {
    if (tree.some((c) => c.parent_id === category.id)) {
      notify('Delete or move its subcategories first.', { title: 'Cannot delete', kind: 'error' });
      return;
    }
    try {
      setDialog({ kind: 'delete', category, inUse: await categoryInUse(api, category.id) });
    } catch (error) {
      notify(errorMessage(error), { kind: 'error' });
    }
  };

  useHotkeys({
    n: () => setDialog({ kind: 'edit', category: null, parentId: null }),
    e: () => selected && setDialog({ kind: 'edit', category: selected, parentId: selected.parent_id }),
    d: () => selected && void askDelete(selected),
    'shift+ArrowUp': () => selected && step(selected, -1),
    'shift+ArrowDown': () => selected && step(selected, 1),
  });

  return (
    <div className="page narrow">
      <PageHeader title="Categories">
        <button
          type="button"
          className="button primary"
          onClick={() => setDialog({ kind: 'edit', category: null, parentId: null })}
        >
          + New category
        </button>
      </PageHeader>
      {categories.isLoading ? (
        <Loading />
      ) : tree.length === 0 ? (
        <Empty>No categories yet: create Food, Home, Salary… and subcategories such as Food › Groceries.</Empty>
      ) : (
        <div className="card">
          <table className="table rows-clickable">
            <thead>
              <tr>
                <th className="handle-cell" aria-label="Reorder" />
                <th>Name</th>
                <th>Symbol</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {visible.map((category) => {
                const edit = () => setDialog({ kind: 'edit', category, parentId: category.parent_id });
                const open = () => setDialog({ kind: 'transactions', category });
                const hasChildren = parentIds.has(category.id);
                const isOpen = expanded.has(category.id);
                // A parent row folds and unfolds its subcategories; its transactions are in the row menu.
                const activate = hasChildren ? () => toggle(category.id) : open;
                return (
                  <tr
                    key={category.id}
                    ref={sortable.rowRef(category.id)}
                    tabIndex={0}
                    aria-expanded={hasChildren ? isOpen : undefined}
                    className={`${category.parent_id !== null ? 'child' : 'parent'}${category.id === selectedId ? ' selected' : ''} ${sortable.rowClass(category)}`}
                    onFocus={() => setSelectedId(category.id)}
                    onClick={activate}
                    onKeyDown={onEnter(activate)}
                  >
                    <td className="handle-cell" onClick={(e) => e.stopPropagation()}>
                      <DragHandle {...sortable.handleProps(category)} />
                    </td>
                    <td>
                      {category.parent_id !== null ? (
                        category.name
                      ) : (
                        <>
                          <span className="tree-toggle" aria-hidden="true">
                            {hasChildren ? (isOpen ? '▾' : '▸') : ''}
                          </span>
                          <strong>{category.name}</strong>
                        </>
                      )}
                    </td>
                    <td className="muted">{category.symbol}</td>
                    <td className="actions" onClick={(e) => e.stopPropagation()}>
                      <RowMenu
                        actions={[
                          hasChildren && { label: 'Transactions', onSelect: open },
                          { label: 'Edit', onSelect: edit, shortcut: 'e' },
                          category.parent_id === null && {
                            label: 'Add subcategory',
                            onSelect: () => {
                              expand(category.id);
                              setDialog({ kind: 'edit', category: null, parentId: category.id });
                            },
                          },
                          { label: 'Delete', onSelect: () => void askDelete(category), danger: true, shortcut: 'd' },
                        ]}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {sortable.status}
        </div>
      )}
      {dialog?.kind === 'transactions' ? (
        <CategoryTransactions category={dialog.category} onClose={() => setDialog(null)} />
      ) : null}
      {dialog?.kind === 'edit' ? (
        <CategoryForm
          category={dialog.category}
          parentId={dialog.parentId}
          parents={tree.filter((c) => c.parent_id === null && c.id !== dialog.category?.id)}
          onClose={() => setDialog(null)}
        />
      ) : null}
      {dialog?.kind === 'delete' ? (
        <DeleteCategory
          category={dialog.category}
          inUse={dialog.inUse}
          targets={tree.filter((c) => c.id !== dialog.category.id)}
          onClose={() => setDialog(null)}
        />
      ) : null}
    </div>
  );
}

function CategoryForm({
  category,
  parentId,
  parents,
  onClose,
}: {
  category: Category | null;
  parentId: number | null;
  parents: Category[];
  onClose: () => void;
}) {
  const [name, setName] = useState(category?.name ?? '');
  const [symbol, setSymbol] = useState(category?.symbol ?? '');
  const [parent, setParent] = useState<number>(parentId ?? NONE_ID);
  const save = useApiMutation(async (api) => {
    const parent_id = parent || null;
    if (!category) {
      return unwrap(api.POST('/api/v1/categories', { body: { name, parent_id, symbol: optionalText(symbol) } }));
    }
    return unwrap(
      api.PATCH('/api/v1/categories/{category_id}', {
        params: { path: { category_id: category.id } },
        body: {
          name,
          symbol: optionalText(symbol),
          ...(parent_id !== category.parent_id ? { parent_id } : {}),
        },
      }),
    );
  });
  return (
    <FormDialog
      open
      onClose={onClose}
      title={category ? `Edit ${category.name}` : 'New category'}
      onSubmit={() => save.mutateAsync(undefined)}
    >
      <TextField label="Name" value={name} onChange={setName} data-autofocus />
      <TextField label="Symbol" value={symbol} onChange={setSymbol} placeholder="derived from the name" maxLength={8} />
      <SelectField
        label="Parent"
        value={parent}
        options={[{ value: NONE_ID, label: '(top level)' }, ...parents.map((p) => ({ value: p.id, label: p.name }))]}
        onChange={setParent}
      />
    </FormDialog>
  );
}

function DeleteCategory({
  category,
  inUse,
  targets,
  onClose,
}: {
  category: Category;
  inUse: boolean;
  targets: Category[];
  onClose: () => void;
}) {
  const [target, setTarget] = useState<number>(NONE_ID);
  const names = byId(targets);
  const remove = useApiMutation((api) =>
    unwrap(
      api.DELETE('/api/v1/categories/{category_id}', {
        params: {
          path: { category_id: category.id },
          query: inUse ? (target ? { reassign_to: target } : { uncategorize: true }) : {},
        },
      }),
    ),
  );
  return (
    <FormDialog
      open
      onClose={onClose}
      title={`Delete category “${category.name}”?`}
      saveLabel="Delete"
      danger
      onSubmit={() => remove.mutateAsync(undefined)}
      help={inUse ? 'The category is used by transactions. Its budgets are deleted.' : 'Its budgets are deleted too.'}
    >
      {inUse ? (
        <SelectField
          label="Move its splits to"
          value={target}
          options={[
            { value: NONE_ID, label: 'Uncategorized' },
            ...targets.map((c) => ({ value: c.id, label: categoryLabel(c.id, names) })),
          ]}
          onChange={setTarget}
        />
      ) : null}
    </FormDialog>
  );
}
