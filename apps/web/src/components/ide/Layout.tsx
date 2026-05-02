import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels';

import { usePanelLayout } from '../../hooks/ide';

type Props = {
  topBar: React.ReactNode;
  fileTree: React.ReactNode;
  editor: React.ReactNode;
  terminal: React.ReactNode;
  chats: React.ReactNode;
};

export function Layout({ topBar, fileTree, editor, terminal, chats }: Props): JSX.Element {
  const { sizes, setLeft, setRight, setBottom } = usePanelLayout();
  return (
    <div className="h-screen flex flex-col bg-ide-bg text-ide-text">
      <div className="border-b border-ide-border bg-ide-deep">{topBar}</div>
      <div className="flex-1 min-h-0">
        <PanelGroup direction="horizontal">
          <Panel
            defaultSize={sizes.left}
            minSize={10}
            collapsible
            onResize={setLeft}
            className="bg-ide-panel"
          >
            {fileTree}
          </Panel>
          <PanelResizeHandle className="w-px bg-ide-borderSoft hover:bg-ide-accent active:bg-ide-accentHover transition-colors" />
          <Panel minSize={20}>
            <PanelGroup direction="vertical">
              <Panel defaultSize={100 - sizes.bottom} minSize={20} className="bg-ide-bg">
                {editor}
              </Panel>
              <PanelResizeHandle className="h-px bg-ide-borderSoft hover:bg-ide-accent active:bg-ide-accentHover transition-colors" />
              <Panel
                defaultSize={sizes.bottom}
                minSize={10}
                collapsible
                onResize={setBottom}
                className="bg-ide-bg border-t border-ide-borderSoft"
              >
                {terminal}
              </Panel>
            </PanelGroup>
          </Panel>
          <PanelResizeHandle className="w-px bg-ide-borderSoft hover:bg-ide-accent active:bg-ide-accentHover transition-colors" />
          <Panel
            defaultSize={sizes.right}
            minSize={10}
            collapsible
            onResize={setRight}
            className="relative bg-ide-panel"
          >
            {chats}
          </Panel>
        </PanelGroup>
      </div>
    </div>
  );
}
