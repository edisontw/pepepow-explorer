'use strict';

const { snapshotOutpoints, buildPruneQuery } = require('../lib/masternode-snapshot');

describe('Masternode full-snapshot pruning', () => {
  const offline = `${'a'.repeat(64)}-1`;
  const enabled = `${'b'.repeat(64)}-0`;
  const full = {
    [offline]: 'NEW_START_REQUIRED 70521 ... lastseen months ago',
    [enabled]: 'ENABLED 70521 ...',
  };
  const tiers = { [offline]: 'T1', [enabled]: 'T4' };

  it('keeps registered offline nodes regardless of old lastseen', () => {
    const query = buildPruneQuery(full, tiers);
    expect(query.$nor).toEqual([
      { txhash: 'a'.repeat(64), outidx: 1 },
      { txhash: 'b'.repeat(64), outidx: 0 },
    ]);
  });

  it('supports object and array full-list payloads', () => {
    expect(snapshotOutpoints(full)).toEqual([offline, enabled]);
    expect(buildPruneQuery([
      { txhash: 'a'.repeat(64), outidx: 1 },
      { txhash: 'b'.repeat(64), outidx: 0 },
    ], tiers).$nor).toHaveSize(2);
  });

  it('never prunes on missing, partial or malformed RPC responses', () => {
    expect(buildPruneQuery(full, null)).toBeNull();
    expect(buildPruneQuery(full, { [offline]: 'T1' })).toBeNull();
    expect(buildPruneQuery({}, {})).toBeNull();
    expect(buildPruneQuery({ bad: 'ENABLED' }, { bad: 'T1' })).toBeNull();
    expect(buildPruneQuery([{}, {}], tiers)).toBeNull();
  });
});
