import { Component, type ReactNode } from 'react';

import { Button } from './ui/button';

export class PageErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <section role="alert" className="rounded-lg border border-[var(--border)] p-6">
        <h2 className="font-semibold">页面加载失败</h2>
        <p className="my-3 text-sm text-[var(--text-muted)]">
          页面可能已更新，或网络暂时不可用。请刷新页面重新加载；已保存的研究结果仍然保留。
        </p>
        <Button
          onClick={() => {
            window.location.reload();
          }}
        >
          刷新页面
        </Button>
      </section>
    );
  }
}
