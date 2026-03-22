import { useState } from 'react';
import { ChevronUp, ChevronDown } from 'lucide-react';

export default function DataTable({ columns = [], data = [], onRowClick }) {
  const [sortKey,   setSortKey]   = useState(null);
  const [sortDir,   setSortDir]   = useState('asc');
  const [expanded,  setExpanded]  = useState(null);

  function handleSort(key) {
    if (sortKey === key) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
  }

  const sorted = sortKey
    ? [...data].sort((a, b) => {
        const av = a[sortKey], bv = b[sortKey];
        if (av == null) return 1;
        if (bv == null) return -1;
        const cmp = av < bv ? -1 : av > bv ? 1 : 0;
        return sortDir === 'asc' ? cmp : -cmp;
      })
    : data;

  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="data-table">
        <thead>
          <tr>
            {columns.map(col => (
              <th
                key={col.key}
                style={{ width: col.width, cursor: col.sortable ? 'pointer' : 'default', userSelect: 'none' }}
                onClick={col.sortable ? () => handleSort(col.key) : undefined}
              >
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                  {col.label}
                  {col.sortable && sortKey === col.key && (
                    sortDir === 'asc'
                      ? <ChevronUp size={11} style={{ color: 'var(--accent-cyan)' }} />
                      : <ChevronDown size={11} style={{ color: 'var(--accent-cyan)' }} />
                  )}
                  {col.sortable && sortKey !== col.key && (
                    <ChevronUp size={11} style={{ opacity: 0.2 }} />
                  )}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length}
                style={{ textAlign: 'center', color: 'var(--text-dim)', padding: '24px' }}
              >
                No data
              </td>
            </tr>
          ) : sorted.map((row, i) => {
            const isExpanded = expanded === i;
            return (
              <tr
                key={i}
                style={{ cursor: onRowClick ? 'pointer' : 'default' }}
                onClick={() => {
                  if (onRowClick) onRowClick(row);
                  setExpanded(isExpanded ? null : i);
                }}
              >
                {columns.map(col => (
                  <td key={col.key}>
                    {col.render ? col.render(row[col.key], row) : (row[col.key] ?? '—')}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
