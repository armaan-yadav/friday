interface Props { count: number; onExport: () => void; onClear: () => void }

export default function Footer({ count, onExport, onClear }: Props) {
  return (
    <footer className="fixed bottom-0 inset-x-0 z-50 h-[56px] flex items-center justify-between px-6 bg-bg/85 backdrop-blur-xl border-t border-white/[0.06]">
      <span className="font-mono text-[0.58rem] tracking-widest uppercase text-text3">
        {count} {count === 1 ? 'exchange' : 'exchanges'}
      </span>
      <div className="flex gap-2">
        {[{ label: 'export', onClick: onExport }, { label: 'clear', onClick: onClear }].map(({ label, onClick }) => (
          <button key={label} onClick={onClick}
            className="font-mono text-[0.58rem] tracking-widest uppercase px-3 py-1.5 rounded border border-white/[0.06] text-text3 hover:text-text2 hover:border-white/10 transition-colors duration-150">
            {label}
          </button>
        ))}
      </div>
    </footer>
  )
}
