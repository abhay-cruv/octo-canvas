import { useTerminal } from '../../hooks/ide';

type Props = { sandboxId: string; terminalId: string; visible: boolean };

/** Mounts xterm + PTY for ONE slot. Visibility is controlled by the parent
 * tab manager — when we're not the active tab, we hide via display:none so
 * the xterm + PTY stay alive (preserves scrollback + the running shell). */
export function Terminal({ sandboxId, terminalId, visible }: Props): JSX.Element {
  const term = useTerminal(sandboxId, terminalId);
  return (
    <div
      ref={term.ref}
      className="h-full w-full bg-ide-bg p-1.5"
      style={{ display: visible ? 'block' : 'none' }}
      onClick={() => term.focus()}
    />
  );
}
