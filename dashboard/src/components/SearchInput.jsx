import { Search } from 'lucide-react';
import { useState } from 'react';

export default function SearchInput({ value, onChange, placeholder = 'Search…' }) {
  const [focused, setFocused] = useState(false);

  return (
    <div style={{
      display:     'flex',
      alignItems:  'center',
      gap:         '8px',
      background:  'var(--bg-tertiary)',
      border:      `1px solid ${focused ? 'var(--accent-cyan)' : 'var(--border-default)'}`,
      borderRadius:'6px',
      padding:     '6px 10px',
      transition:  'border-color 0.15s',
    }}>
      <Search size={13} style={{ color: 'var(--text-muted)', flexShrink: 0 }} />
      <input
        type="text"
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        style={{
          background:  'none',
          border:      'none',
          outline:     'none',
          color:       'var(--text-primary)',
          fontFamily:  'var(--font-mono)',
          fontSize:    '12px',
          width:       '100%',
        }}
      />
    </div>
  );
}
