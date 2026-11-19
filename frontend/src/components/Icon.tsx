const paths = {
  upload: 'M12 16V3m-5 5 5-5 5 5M4 15v5h16v-5',
  chat: 'M21 15a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2Z',
  folder: 'M3 7V4h7l2 3h9v13H3Z',
  file: 'M14 2H5v20h14V7Zm0 0v5h5M8 12h8m-8 4h8',
  search: 'm21 21-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
  plus: 'M12 4v16M4 12h16',
  refresh: 'M20 7V2m0 5h-5m5 0a9 9 0 1 0 1 9',
  send: 'm3 3 19 9-19 9 4-9Zm4 9h15',
  clip: 'm8 12 7-7a4 4 0 0 1 6 6L10 22a6 6 0 0 1-8-8L13 3m-8 14 11-11',
  expand: 'M8 3H3v5m13-5h5v5M3 16v5h5m8 0h5v-5',
  download: 'M12 3v12m-5-5 5 5 5-5M4 17v4h16v-4',
  trash: 'M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7',
  warning: 'm12 3 10 18H2Zm0 5v5m0 4v.1',
  check: 'M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0m-16 0 4 4 8-8',
  help: 'M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0M9 8a3 3 0 1 1 4 3c-1 .5-1 1-1 3m0 3v.1',
}

export default function Icon({ name, size = 20 }: { name: keyof typeof paths; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]} /></svg>
}
