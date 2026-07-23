import React, { useCallback, useEffect, useState } from 'react';
import {
  ArrowLeft, Search, Boxes, Layers, FileText, Wallet as WalletIcon,
  Shield, Coins, Package, RefreshCw,
} from 'lucide-react';

// Privacy-aware block explorer. The base UTXO layer is transparent and
// auditable by design; shielded "Ghost" transactions expose only their
// validity (amounts/parties stay hidden). All reads go through the gateway's
// /api/explorer/* endpoints, which enforce the redaction server-side.
const BlockExplorer = ({ onBack }) => {
  const backendUrl = process.env.REACT_APP_BACKEND_URL || '';

  const [view, setView] = useState('overview'); // overview | block | tx | address
  const [info, setInfo] = useState(null);
  const [blocks, setBlocks] = useState([]);
  const [detail, setDetail] = useState(null);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const api = useCallback(async (path) => {
    const res = await fetch(`${backendUrl}/api/explorer/${path}`);
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed (${res.status})`);
    }
    return res.json();
  }, [backendUrl]);

  const loadOverview = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [i, b] = await Promise.all([
        api('info').catch(() => null),
        api('blocks/latest?limit=20').catch(() => ({ blocks: [] })),
      ]);
      setInfo(i && i.data ? i.data : null);
      setBlocks((b && b.blocks) || []);
    } catch (e) {
      setError(e.message || 'Failed to load explorer');
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => { loadOverview(); }, [loadOverview]);

  const openBlock = async (identifier) => {
    setLoading(true); setError('');
    try {
      const r = await api(`block/${identifier}`);
      setDetail(r.block); setView('block');
    } catch (e) { setError(e.message); } finally { setLoading(false); }
  };

  const openTx = async (txid) => {
    setLoading(true); setError('');
    try {
      const r = await api(`tx/${txid}`);
      setDetail(r.transaction); setView('tx');
    } catch (e) { setError(e.message); } finally { setLoading(false); }
  };

  const openAddress = async (address) => {
    setLoading(true); setError('');
    try {
      const r = await api(`address/${address}`);
      setDetail(r); setView('address');
    } catch (e) { setError(e.message); } finally { setLoading(false); }
  };

  const doSearch = async (e) => {
    e && e.preventDefault();
    const q = query.trim();
    if (!q) return;
    setLoading(true); setError('');
    try {
      const r = await api(`search?q=${encodeURIComponent(q)}`);
      if (r.type === 'block') await openBlock(r.id);
      else if (r.type === 'tx') await openTx(r.id);
      else if (r.type === 'address') await openAddress(r.id);
    } catch (e2) {
      setError(e2.message || 'Nothing found for that query');
    } finally { setLoading(false); }
  };

  const backToOverview = () => { setView('overview'); setDetail(null); setError(''); };
  const fmtTime = (ts) => (ts ? new Date(ts * 1000).toLocaleString() : '—');
  const shortHash = (h) => (h && h.length > 20 ? `${h.slice(0, 10)}…${h.slice(-8)}` : h || '—');

  const SearchBar = () => (
    <form onSubmit={doSearch} className="flex gap-2 mb-6">
      <div className="relative flex-1">
        <Search className="h-4 w-4 text-gray-500 absolute left-3 top-1/2 -translate-y-1/2" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by block height, block hash, txid, or wepo1 address"
          className="w-full bg-gray-900/70 border border-purple-500/30 rounded-lg pl-9 pr-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-purple-400"
        />
      </div>
      <button type="submit" className="bg-purple-600 hover:bg-purple-500 text-white px-4 py-2 rounded-lg text-sm font-medium">Search</button>
    </form>
  );

  const TypeBadge = ({ tx }) => {
    if (tx.shielded) return <span className="inline-flex items-center gap-1 text-xs bg-purple-900/50 text-purple-300 px-2 py-0.5 rounded"><Shield className="h-3 w-3" /> Shielded</span>;
    if (tx.coinbase) return <span className="inline-flex items-center gap-1 text-xs bg-yellow-900/40 text-yellow-300 px-2 py-0.5 rounded"><Coins className="h-3 w-3" /> Coinbase</span>;
    if (tx.tx_type === 'rwa_create') return <span className="inline-flex items-center gap-1 text-xs bg-emerald-900/40 text-emerald-300 px-2 py-0.5 rounded"><Package className="h-3 w-3" /> RWA</span>;
    if (tx.tx_type === 'key_register') return <span className="text-xs bg-blue-900/40 text-blue-300 px-2 py-0.5 rounded">Key anchor</span>;
    return <span className="text-xs bg-gray-700/60 text-gray-300 px-2 py-0.5 rounded">{tx.tx_type || 'transfer'}</span>;
  };

  const Overview = () => (
    <div>
      <SearchBar />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        {[
          ['Height', info?.height ?? info?.block_height ?? info?.blocks ?? '—'],
          ['Total supply', info?.total_supply != null ? `${Number(info.total_supply).toLocaleString()} WEPO` : '—'],
          ['Supply cap', info?.supply_cap != null ? `${Number(info.supply_cap / 1e8 || info.supply_cap).toLocaleString()}` : '69,000,003'],
          ['Consensus', info?.consensus || info?.mining_mode || 'PoW/PoS'],
        ].map(([label, val]) => (
          <div key={label} className="bg-gray-900/60 border border-purple-500/20 rounded-lg p-3">
            <div className="text-gray-400 text-xs">{label}</div>
            <div className="text-white font-semibold text-sm mt-1 break-words">{String(val)}</div>
          </div>
        ))}
      </div>

      <div className="flex items-center justify-between mb-2">
        <h3 className="text-white font-semibold flex items-center gap-2"><Layers className="h-4 w-4 text-purple-400" /> Latest blocks</h3>
        <button onClick={loadOverview} className="text-gray-400 hover:text-white"><RefreshCw className="h-4 w-4" /></button>
      </div>
      <div className="bg-gray-900/40 border border-purple-500/20 rounded-lg divide-y divide-gray-800">
        {blocks.length === 0 && <div className="p-4 text-sm text-gray-500">No blocks yet.</div>}
        {blocks.map((b) => (
          <button key={b.hash || b.height} onClick={() => openBlock(String(b.height))} className="w-full text-left p-3 hover:bg-gray-800/40 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Boxes className="h-4 w-4 text-blue-400" />
              <div>
                <div className="text-white text-sm font-medium">#{b.height}</div>
                <div className="text-gray-500 text-xs font-mono">{shortHash(b.hash)}</div>
              </div>
            </div>
            <div className="text-right">
              <div className="text-gray-300 text-xs">{b.tx_count ?? 0} tx · {b.consensus_type || '—'}</div>
              <div className="text-gray-500 text-xs">{fmtTime(b.timestamp)}</div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );

  const BlockDetail = () => (
    <div>
      <SearchBar />
      <h3 className="text-white font-semibold mb-3 flex items-center gap-2"><Boxes className="h-4 w-4 text-blue-400" /> Block #{detail?.height}</h3>
      <div className="bg-gray-900/60 border border-purple-500/20 rounded-lg p-4 text-sm space-y-2">
        <Row k="Hash" v={detail?.hash} mono />
        <Row k="Previous" v={detail?.prev_hash} mono />
        <Row k="Merkle root" v={detail?.merkle_root} mono />
        <Row k="Timestamp" v={fmtTime(detail?.timestamp)} />
        <Row k="Consensus" v={detail?.consensus_type} />
        <Row k="Nonce" v={detail?.nonce} />
        <Row k="Size" v={detail?.size != null ? `${detail.size} bytes` : '—'} />
      </div>
      <h4 className="text-white font-medium mt-5 mb-2">Transactions ({(detail?.transactions || []).length})</h4>
      <div className="bg-gray-900/40 border border-purple-500/20 rounded-lg divide-y divide-gray-800">
        {(detail?.transactions || []).map((txid) => (
          <button key={txid} onClick={() => openTx(txid)} className="w-full text-left p-3 hover:bg-gray-800/40 flex items-center gap-2">
            <FileText className="h-4 w-4 text-gray-400" />
            <span className="text-gray-300 text-xs font-mono">{shortHash(txid)}</span>
          </button>
        ))}
      </div>
    </div>
  );

  const TxDetail = () => (
    <div>
      <SearchBar />
      <div className="flex items-center gap-2 mb-3">
        <FileText className="h-4 w-4 text-purple-400" />
        <h3 className="text-white font-semibold">Transaction</h3>
        <TypeBadge tx={detail || {}} />
      </div>
      <div className="bg-gray-900/60 border border-purple-500/20 rounded-lg p-4 text-sm space-y-2">
        <Row k="Txid" v={detail?.txid} mono />
        <Row k="Block" v={detail?.block_height != null ? `#${detail.block_height}` : 'pending'} />
        <Row k="Confirmations" v={detail?.confirmations ?? 0} />
        <Row k="Fee" v={detail?.fee != null ? `${detail.fee} WEPO` : '—'} />
        <Row k="Time" v={fmtTime(detail?.timestamp)} />
      </div>

      {detail?.shielded ? (
        <div className="mt-4 bg-purple-900/20 border border-purple-500/30 rounded-lg p-4 text-sm text-purple-200 flex gap-2">
          <Shield className="h-5 w-5 flex-shrink-0 text-purple-400" />
          <span>{detail.note}</span>
        </div>
      ) : (
        <>
          {detail?.asset && (
            <div className="mt-4 bg-emerald-900/20 border border-emerald-500/30 rounded-lg p-4 text-sm space-y-1">
              <div className="text-emerald-300 font-medium flex items-center gap-1"><Package className="h-4 w-4" /> RWA asset</div>
              <Row k="Asset ID" v={detail.asset.asset_id} mono />
              <Row k="Name" v={detail.asset.name} />
              <Row k="Type" v={detail.asset.asset_type} />
              <Row k="Asset hash" v={detail.asset.asset_hash} mono />
            </div>
          )}
          <div className="grid md:grid-cols-2 gap-4 mt-4">
            <div>
              <h4 className="text-white font-medium mb-2">Inputs ({(detail?.inputs || []).length})</h4>
              <div className="bg-gray-900/40 border border-purple-500/20 rounded-lg p-3 space-y-2">
                {(detail?.inputs || []).map((inp, i) => (
                  <div key={i} className="text-xs text-gray-400 font-mono break-all">
                    {inp.prev_txid ? `${shortHash(inp.prev_txid)}:${inp.prev_vout}` : 'coinbase'}
                  </div>
                ))}
                {(detail?.inputs || []).length === 0 && <div className="text-xs text-gray-500">—</div>}
              </div>
            </div>
            <div>
              <h4 className="text-white font-medium mb-2">Outputs ({(detail?.outputs || []).length})</h4>
              <div className="bg-gray-900/40 border border-purple-500/20 rounded-lg p-3 space-y-2">
                {(detail?.outputs || []).map((out, i) => (
                  <button key={i} onClick={() => out.address && openAddress(out.address)} className="w-full text-left text-xs">
                    <span className="text-gray-300 font-mono break-all">{out.address ? shortHash(out.address) : '—'}</span>
                    <span className="text-green-400 float-right">{out.value != null ? `${out.value} WEPO` : ''}</span>
                  </button>
                ))}
                {(detail?.outputs || []).length === 0 && <div className="text-xs text-gray-500">—</div>}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );

  const AddressDetail = () => (
    <div>
      <SearchBar />
      <h3 className="text-white font-semibold mb-3 flex items-center gap-2"><WalletIcon className="h-4 w-4 text-blue-400" /> Address</h3>
      <div className="bg-gray-900/60 border border-purple-500/20 rounded-lg p-4 text-sm space-y-2">
        <Row k="Address" v={detail?.address} mono />
        <Row k="Balance" v={detail?.info?.balance != null ? `${detail.info.balance} WEPO` : '—'} />
        <Row k="Received" v={detail?.info?.total_received != null ? `${detail.info.total_received} WEPO` : '—'} />
        <Row k="Sent" v={detail?.info?.total_sent != null ? `${detail.info.total_sent} WEPO` : '—'} />
        <Row k="UTXOs" v={detail?.info?.utxo_count ?? '—'} />
      </div>
      <h4 className="text-white font-medium mt-5 mb-2">Activity ({(detail?.transactions || []).length})</h4>
      <div className="bg-gray-900/40 border border-purple-500/20 rounded-lg divide-y divide-gray-800">
        {(detail?.transactions || []).map((t, i) => (
          <button key={t.txid || i} onClick={() => t.txid && openTx(t.txid)} className="w-full text-left p-3 hover:bg-gray-800/40 flex items-center justify-between">
            <div>
              <div className="text-gray-300 text-xs font-mono">{shortHash(t.txid)}</div>
              <div className="text-gray-500 text-xs">{t.type || 'transfer'} · {fmtTime(t.timestamp)}</div>
            </div>
            <div className={`text-xs ${t.type === 'send' ? 'text-red-400' : 'text-green-400'}`}>
              {t.amount != null ? `${t.amount} WEPO` : ''}
            </div>
          </button>
        ))}
        {(detail?.transactions || []).length === 0 && <div className="p-4 text-sm text-gray-500">No activity.</div>}
      </div>
    </div>
  );

  return (
    <div className="bg-gray-800/40 border border-purple-500/20 rounded-2xl p-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <button onClick={view === 'overview' ? onBack : backToOverview} className="text-gray-400 hover:text-white"><ArrowLeft className="h-5 w-5" /></button>
          <h2 className="text-xl font-bold text-white">Block Explorer</h2>
        </div>
        <span className="text-xs text-gray-500">Transparent base layer · shielded tx hidden by design</span>
      </div>

      {error && <div className="mb-4 bg-red-900/30 border border-red-500/30 rounded-lg p-3 text-sm text-red-300">{error}</div>}
      {loading && <div className="mb-4 text-sm text-gray-400 flex items-center gap-2"><RefreshCw className="h-4 w-4 animate-spin" /> Loading…</div>}

      {view === 'overview' && <Overview />}
      {view === 'block' && <BlockDetail />}
      {view === 'tx' && <TxDetail />}
      {view === 'address' && <AddressDetail />}
    </div>
  );
};

const Row = ({ k, v, mono }) => (
  <div className="flex justify-between gap-4">
    <span className="text-gray-400 flex-shrink-0">{k}</span>
    <span className={`text-white text-right break-all ${mono ? 'font-mono text-xs' : ''}`}>{v ?? '—'}</span>
  </div>
);

export default BlockExplorer;
