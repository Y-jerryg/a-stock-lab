import {
  Activity,
  Bot,
  ChartNoAxesCombined,
  ChevronRight,
  Database,
  Gauge,
  Menu,
  Moon,
  Radar,
  Sun,
  X,
  type LucideIcon,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';

import { Button } from '../components/ui/button';
import { PageErrorBoundary } from '../components/PageErrorBoundary';
import { cn } from '../lib/utils';
import { text } from '../locales';

type Theme = 'light' | 'dark';

interface NavItem {
  label: string;
  path: string;
  icon: LucideIcon;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

const navigation: NavGroup[] = [
  { label: '工作台', items: [{ label: '总览', path: '/', icon: Gauge }] },
  {
    label: '研究',
    items: [
      { label: '尾盘雷达', path: '/tail-radar', icon: Radar },
      { label: text.trend.nav, path: '/trend-radar', icon: ChartNoAxesCombined },
      { label: '情报中心', path: '/intelligence', icon: Activity },
      { label: '量化实验室', path: '/quant-lab', icon: ChartNoAxesCombined },
    ],
  },
  { label: '人工智能', items: [{ label: 'AI 研究助手', path: '/assistant', icon: Bot }] },
  { label: '系统', items: [{ label: '数据状态', path: '/data-status', icon: Database }] },
];

function getInitialTheme(): Theme {
  const saved = localStorage.getItem('a-stock-lab-theme');
  if (saved === 'light' || saved === 'dark') return saved;
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export function AppShell() {
  const [isSidebarOpen, setSidebarOpen] = useState(false);
  const [theme, setTheme] = useState<Theme>(getInitialTheme);
  const location = useLocation();

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('a-stock-lab-theme', theme);
  }, [theme]);

  useEffect(() => {
    setSidebarOpen(false);
  }, [location.pathname]);

  return (
    <div className="min-h-screen bg-[var(--canvas)] text-[var(--text-primary)]">
      <div
        className={cn(
          'fixed inset-0 z-30 bg-slate-950/45 backdrop-blur-sm lg:hidden',
          isSidebarOpen ? 'block' : 'hidden',
        )}
        onClick={() => {
          setSidebarOpen(false);
        }}
        aria-hidden="true"
      />
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r border-[var(--border)] bg-[var(--sidebar)] transition-transform duration-200 lg:translate-x-0',
          isSidebarOpen ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        <div className="flex h-16 items-center justify-between border-b border-[var(--border)] px-5">
          <NavLink to="/" className="flex items-center gap-3" aria-label="A股实验室首页">
            <div className="grid size-8 place-items-center rounded-md bg-[var(--accent)] text-sm font-bold text-white shadow-sm">
              A
            </div>
            <div>
              <p className="text-sm font-semibold tracking-tight">A股实验室</p>
              <p className="text-[10px] font-medium tracking-[0.16em] text-[var(--text-muted)] uppercase">
                研究系统
              </p>
            </div>
          </NavLink>
          <Button
            variant="ghost"
            size="icon"
            className="lg:hidden"
            onClick={() => {
              setSidebarOpen(false);
            }}
            aria-label="关闭导航栏"
          >
            <X className="size-4" />
          </Button>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-5" aria-label="主导航栏">
          {navigation.map((group) => (
            <div key={group.label} className="mb-6">
              <p className="mb-2 px-3 text-[10px] font-semibold tracking-[0.14em] text-[var(--text-subtle)] uppercase">
                {group.label}
              </p>
              <div className="space-y-1">
                {group.items.map((item) => {
                  const Icon = item.icon;
                  return (
                    <NavLink
                      key={item.path}
                      to={item.path}
                      end={item.path === '/'}
                      className={({ isActive }) =>
                        cn(
                          'group flex h-10 items-center gap-3 rounded-md px-3 text-sm font-medium transition-colors',
                          isActive
                            ? 'bg-[var(--nav-active)] text-[var(--text-primary)]'
                            : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)]',
                        )
                      }
                    >
                      {({ isActive }) => (
                        <>
                          <Icon
                            className={cn(
                              'size-4',
                              isActive ? 'text-[var(--accent)]' : 'text-[var(--text-subtle)]',
                            )}
                          />
                          <span className="flex-1 truncate">{item.label}</span>
                          {isActive && <ChevronRight className="size-3.5 text-[var(--accent)]" />}
                        </>
                      )}
                    </NavLink>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        <div className="border-t border-[var(--border)] p-4">
          <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-2.5">
            <div className="flex items-center gap-2 text-xs font-medium">
              <span className="size-1.5 rounded-full bg-emerald-500" />
              基础环境
            </div>
            <p className="mt-1 pl-3.5 text-[11px] text-[var(--text-subtle)]">尾盘雷达 · 时点快照</p>
          </div>
        </div>
      </aside>

      <div className="lg:pl-72">
        <header className="sticky top-0 z-20 flex h-16 items-center justify-between border-b border-[var(--border)] bg-[color-mix(in_srgb,var(--canvas)_88%,transparent)] px-4 backdrop-blur-md sm:px-6 lg:px-8">
          <div className="flex items-center gap-3">
            <Button
              variant="ghost"
              size="icon"
              className="lg:hidden"
              onClick={() => {
                setSidebarOpen(true);
              }}
              aria-label="打开导航栏"
            >
              <Menu className="size-4" />
            </Button>
            <div>
              <p className="text-xs font-medium text-[var(--text-muted)]">A股研究工作台</p>
              <p className="hidden text-[10px] text-[var(--text-subtle)] sm:block">
                市场标准时区 · 亚洲/上海
              </p>
            </div>
          </div>
          <Button
            variant="outline"
            size="icon"
            onClick={() => {
              setTheme(theme === 'dark' ? 'light' : 'dark');
            }}
            aria-label={`切换为${theme === 'dark' ? '浅色' : '深色'}主题`}
          >
            {theme === 'dark' ? <Sun className="size-4" /> : <Moon className="size-4" />}
          </Button>
        </header>
        <main className="mx-auto w-full max-w-[1600px] p-4 sm:p-6 lg:p-8">
          <PageErrorBoundary key={location.pathname}>
            <Outlet />
          </PageErrorBoundary>
        </main>
      </div>
    </div>
  );
}
