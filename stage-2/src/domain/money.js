'use strict';
// Money rules from §9 (equal split) and §11 (net settlement affordability).

// Equal split: whole units, sum to amount, differ by at most one; larger shares first.
function splitShares(amount, n) {
  const base = Math.floor(amount / n);
  const extra = amount - base * n;
  const shares = [];
  for (let i = 0; i < n; i++) shares.push(base + (i < extra ? 1 : 0));
  return shares;
}

// Net movement per wallet for a batch of transfers {from, to, amount}.
function netChanges(transfers) {
  const net = new Map();
  for (const t of transfers) {
    net.set(t.from, (net.get(t.from) || 0) - t.amount);
    net.set(t.to, (net.get(t.to) || 0) + t.amount);
  }
  return net;
}

// A batch is affordable when every wallet ends nonnegative. balanceOf(id) -> number.
function affordable(transfers, balanceOf) {
  for (const [id, delta] of netChanges(transfers)) {
    if (balanceOf(id) + delta < 0) return false;
  }
  return true;
}

module.exports = { splitShares, netChanges, affordable };
