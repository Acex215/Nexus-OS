export const COLORS = {
  cyan:   '#06b6d4',
  green:  '#10b981',
  red:    '#ef4444',
  amber:  '#f59e0b',
  blue:   '#3b82f6',
  purple: '#8b5cf6',
};

export const CHART_COLORS = [
  COLORS.cyan,
  COLORS.green,
  COLORS.blue,
  COLORS.amber,
  COLORS.purple,
  COLORS.red,
];

export const NODE_COLORS = {
  'nexus-admin':   COLORS.cyan,
  'nexus-master':  COLORS.green,
  'nexus-ai':      COLORS.purple,
  'nexus-ai2':     COLORS.amber,
  'nexus-storage': COLORS.blue,
  'ThinkStation':  COLORS.red,
  'ThinkPad':      '#f472b6',
};

export function formatAddress(addr) {
  if (!addr) return '—';
  return `${addr.slice(0, 6)}...${addr.slice(-4)}`;
}

export function formatTime(ts) {
  if (!ts) return '—';
  const now  = Date.now();
  const then = typeof ts === 'number' && ts < 1e12 ? ts * 1000 : new Date(ts).getTime();
  const diff = Math.floor((now - then) / 1000);
  if (diff < 5)    return 'just now';
  if (diff < 60)   return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export function formatBytes(bytes) {
  if (bytes == null || isNaN(bytes)) return '—';
  const abs = Math.abs(bytes);
  if (abs < 1024)             return `${bytes} B`;
  if (abs < 1024 ** 2)        return `${(bytes / 1024).toFixed(1)} KB`;
  if (abs < 1024 ** 3)        return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  if (abs < 1024 ** 4)        return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  return `${(bytes / 1024 ** 4).toFixed(1)} TB`;
}

export function formatPercent(value) {
  if (value == null || isNaN(value)) return '—';
  return `${Math.round(value)}%`;
}
