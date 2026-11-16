import { useMemo, useState, type KeyboardEvent } from 'react';
import { Modal } from '../components/Modal';

export interface Command {
  id: string;
  label: string;
  hint?: string;
  run: () => void;
}

export function CommandPalette({ open, onClose, commands }: { open: boolean; onClose: () => void; commands: Command[] }) {
  const [text, setText] = useState('');
  const [index, setIndex] = useState(0);
  const matches = useMemo(() => {
    const words = text.toLowerCase().split(/\s+/).filter(Boolean);
    return commands.filter((command) => words.every((word) => command.label.toLowerCase().includes(word)));
  }, [commands, text]);

  const run = (command: Command | undefined) => {
    if (!command) return;
    onClose();
    setText('');
    setIndex(0);
    // Let the palette close before the command opens its own dialog.
    window.setTimeout(command.run, 0);
  };

  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setIndex((i) => Math.min(i + 1, matches.length - 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setIndex((i) => Math.max(i - 1, 0));
    } else if (event.key === 'Enter') {
      event.preventDefault();
      run(matches[index]);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Commands">
      <div className="palette">
        <input
          aria-label="Search commands"
          placeholder="Type a command…"
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setIndex(0);
          }}
          onKeyDown={onKeyDown}
        />
        <ul role="listbox" aria-label="Commands">
          {matches.map((command, i) => (
            <li key={command.id} role="option" aria-selected={i === index}>
              <button type="button" onClick={() => run(command)} onMouseEnter={() => setIndex(i)} tabIndex={-1}>
                <span>{command.label}</span>
                {command.hint ? <kbd>{command.hint}</kbd> : null}
              </button>
            </li>
          ))}
          {matches.length === 0 ? <li className="muted empty">No matching command</li> : null}
        </ul>
      </div>
    </Modal>
  );
}
