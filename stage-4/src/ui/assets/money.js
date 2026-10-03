// Amount formatting and parsing for people, in the service's single currency.

// "100.00 EUR", "1200 JPY", "0.005 BHD": exactly minor_units decimals, one space, the code.
export function formatAmount(minor, mu, currency) {
  return `${decimalString(minor, mu)} ${currency}`;
}

// The decimal part alone, as a person would type it ("15.00").
export function decimalString(minor, mu) {
  const v = Math.abs(minor);
  if (mu === 0) return String(v);
  const base = 10 ** mu;
  return `${Math.floor(v / base)}.${String(v % base).padStart(mu, '0')}`;
}

// "15" / "15.5" / "15.00" -> minor units; null for anything else, including
// more decimal places than the currency has (never rounded).
export function parseAmount(text, mu) {
  const m = /^(\d{1,13})(?:\.(\d+))?$/.exec(String(text).trim());
  if (!m) return null;
  const frac = m[2];
  if (frac !== undefined && (mu === 0 || frac.length > mu)) return null;
  const value = Number(m[1]) * 10 ** mu + (mu ? Number((frac || '').padEnd(mu, '0')) : 0);
  return Number.isSafeInteger(value) ? value : null;
}

// Equal split (stage-1 §9): larger shares go to the first participants.
export function splitShares(amount, n) {
  const base = Math.floor(amount / n);
  const extra = amount - base * n;
  return Array.from({ length: n }, (_, i) => base + (i < extra ? 1 : 0));
}

const timeFmt = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' });
const dayFmt = new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short' });

// "Today, 13:10" / "Yesterday, 09:02" / "24 Sep, 13:10".
export function humanTime(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const today = new Date();
  const startOf = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((startOf(today) - startOf(d)) / 86400000);
  const day = days === 0 ? 'Today' : days === 1 ? 'Yesterday' : dayFmt.format(d);
  return `${day}, ${timeFmt.format(d)}`;
}

// "in 9 min" / "in 2 h" / "3 min ago".
export function relative(iso) {
  const diff = new Date(iso).getTime() - Date.now();
  const abs = Math.abs(diff);
  const text = abs < 60000 ? 'less than a minute'
    : abs < 3600000 ? `${Math.round(abs / 60000)} min`
      : abs < 172800000 ? `${Math.round(abs / 3600000)} h` : `${Math.round(abs / 86400000)} days`;
  return diff >= 0 ? `in ${text}` : `${text} ago`;
}
