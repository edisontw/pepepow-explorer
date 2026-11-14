'use strict';

// A masternode with an old lastseen is still registered if it appears in the
// current Core masternodelist. Prune by a verified complete snapshot, never by
// the last ping timestamp.
const OUTPOINT_RE = /^([a-f0-9]{64})-(\d+)$/i;

function snapshotOutpoints(fullList) {
  if (Array.isArray(fullList)) {
    return fullList.map((entry) => {
      if (!entry || typeof entry !== 'object')
        return null;
      const hash = String(entry.txhash || '');
      if (OUTPOINT_RE.test(hash) && entry.outidx == null)
        return hash;
      return entry.outidx == null ? null : `${hash}-${entry.outidx}`;
    });
  }
  return fullList && typeof fullList === 'object' ? Object.keys(fullList) : [];
}

function buildPruneQuery(fullList, tierMap) {
  const outpoints = snapshotOutpoints(fullList);
  if (!outpoints.length || !tierMap || typeof tierMap !== 'object' || Array.isArray(tierMap))
    return null;

  // Require the independent read-only tier RPC to confirm the complete roster.
  // An unsupported tier RPC, a partial snapshot or changed node membership must
  // never trigger destructive cleanup.
  const tierKeys = Object.keys(tierMap);
  if (outpoints.length !== tierKeys.length)
    return null;

  const seen = new Set();
  const keep = [];
  for (const outpoint of outpoints) {
    const match = typeof outpoint === 'string' ? OUTPOINT_RE.exec(outpoint) : null;
    if (!match || seen.has(outpoint) || !Object.prototype.hasOwnProperty.call(tierMap, outpoint))
      return null;
    const outidx = Number(match[2]);
    if (!Number.isSafeInteger(outidx))
      return null;
    seen.add(outpoint);
    keep.push({ txhash: match[1], outidx });
  }
  return { $nor: keep };
}

module.exports = { snapshotOutpoints, buildPruneQuery };
