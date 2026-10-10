import { Link } from 'react-router-dom';

export function Footer() {
  const year = new Date().getFullYear();

  return (
    <footer className="border-t border-slate-200 bg-white px-6 py-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-xs text-slate-500">
          &copy; {year} E-Waste ChainGuard. All rights reserved.
        </p>
        <nav className="flex flex-wrap gap-x-4 gap-y-1" aria-label="Footer links">
          {[
            { label: 'Privacy Policy', to: '/privacy' },
            { label: 'Terms of Service', to: '/terms' },
            { label: 'Data Processing Agreement', to: '/dpa' },
            { label: 'Contact', to: '/contact' },
          ].map(({ label, to }) => (
            <Link
              key={to}
              to={to}
              className="text-xs text-slate-500 hover:text-slate-800 transition-colors"
            >
              {label}
            </Link>
          ))}
        </nav>
      </div>
    </footer>
  );
}
