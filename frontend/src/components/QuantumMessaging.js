import React, { useState } from 'react';
import {
  ArrowLeft,
  Send,
  MessageCircle,
  Shield,
  Lock,
  Plus,
  X,
  AlertTriangle,
  CheckCircle,
  RefreshCw,
} from 'lucide-react';
import { useWallet } from '../contexts/WalletContext';

/**
 * Quantum private messaging — post-quantum end-to-end (ML-KEM-768 + AES-256-GCM +
 * ML-DSA-44). All crypto runs client-side; the relay only stores opaque
 * ciphertext. The wallet password unlocks the local recovery phrase to derive the
 * messaging + spend keys for this session.
 */
const QuantumMessaging = ({ onBack }) => {
  const { wallet, publishMessagingKeys, registerMessagingKeysOnChain, sendMessage, fetchMessages } = useWallet();
  const currentAddress = wallet?.address;

  const [password, setPassword] = useState('');
  const [unlocked, setUnlocked] = useState(false);
  const [messages, setMessages] = useState([]);      // decrypted received messages
  const [sentLog, setSentLog] = useState([]);        // local echo of sent messages
  const [selected, setSelected] = useState(null);    // selected conversation address
  const [compose, setCompose] = useState({ to_address: '', content: '' });
  const [showCompose, setShowCompose] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [info, setInfo] = useState('');

  const refresh = async (pw = password) => {
    if (!pw) { setError('Enter your wallet password'); return; }
    setIsLoading(true);
    setError('');
    try {
      const inbox = await fetchMessages(pw);
      setMessages(inbox);
      setUnlocked(true);
    } catch (e) {
      setError(e.message || 'Failed to load messages');
    } finally {
      setIsLoading(false);
    }
  };

  const handleEnableMessaging = async () => {
    if (!password) { setError('Enter your wallet password'); return; }
    setIsLoading(true);
    setError('');
    try {
      await publishMessagingKeys(password);
      setInfo('Messaging keys published — others can now send you encrypted messages.');
      await refresh(password);
    } catch (e) {
      setError(e.message || 'Failed to enable messaging');
    } finally {
      setIsLoading(false);
    }
  };

  const handleAnchorOnChain = async () => {
    if (!password) { setError('Enter your wallet password'); return; }
    setIsLoading(true);
    setError('');
    try {
      await registerMessagingKeysOnChain(password);
      setInfo('Messaging keys anchored on-chain — recipients can discover them trustlessly (no registry trust). Confirms in a block.');
    } catch (e) {
      setError(e.message || 'Failed to anchor keys on-chain');
    } finally {
      setIsLoading(false);
    }
  };

  const handleSend = async () => {
    if (!compose.to_address || !compose.content) { setError('Recipient and message are required'); return; }
    if (!password) { setError('Enter your wallet password'); return; }
    setIsLoading(true);
    setError('');
    try {
      await sendMessage(compose.to_address, compose.content, password);
      // Optimistically echo our own sent message into the local view.
      setSentLog((prev) => [...prev, {
        message_id: `local-${Date.now()}`,
        to: compose.to_address,
        plaintext: compose.content,
        ts: Math.floor(Date.now() / 1000),
        mine: true,
      }]);
      setSelected(compose.to_address);
      setCompose({ to_address: '', content: '' });
      setShowCompose(false);
      setInfo('Message sent (end-to-end encrypted).');
    } catch (e) {
      setError(e.message || 'Failed to send message');
    } finally {
      setIsLoading(false);
    }
  };

  const fmt = (ts) => {
    if (!ts) return '';
    const d = new Date(ts * 1000);
    const h = (Date.now() - d.getTime()) / 36e5;
    return h < 1 ? 'Just now' : h < 24 ? `${Math.floor(h)}h ago` : d.toLocaleDateString();
  };

  // Build conversation list from received + sent, grouped by the other address.
  const conversations = (() => {
    const map = new Map();
    const add = (addr, item) => {
      if (!addr) return;
      const cur = map.get(addr);
      if (!cur || (cur.ts || 0) < (item.ts || 0)) map.set(addr, { address: addr, last: item.plaintext, ts: item.ts });
    };
    messages.forEach((m) => add(m.from, m));
    sentLog.forEach((m) => add(m.to, m));
    return Array.from(map.values()).sort((a, b) => (b.ts || 0) - (a.ts || 0));
  })();

  const thread = selected
    ? [
        ...messages.filter((m) => m.from === selected).map((m) => ({ ...m, mine: false })),
        ...sentLog.filter((m) => m.to === selected),
      ].sort((a, b) => (a.ts || 0) - (b.ts || 0))
    : [];

  const Header = () => (
    <div className="flex items-center gap-3 mb-6">
      <button onClick={onBack} className="text-gray-400 hover:text-white transition-colors"><ArrowLeft size={24} /></button>
      <div className="flex items-center gap-2">
        <Shield className="h-6 w-6 text-purple-400" />
        <h2 className="text-xl font-semibold text-white">Quantum Messaging</h2>
      </div>
    </div>
  );

  const Alerts = () => (
    <>
      {error && <div className="bg-red-900/50 border border-red-500 rounded-lg p-3 text-red-200 text-sm mb-3">{error}</div>}
      {info && <div className="bg-green-900/40 border border-green-500 rounded-lg p-3 text-green-200 text-sm mb-3">{info}</div>}
    </>
  );

  if (!currentAddress) {
    return (
      <div className="space-y-6"><Header />
        <div className="bg-yellow-900/30 border border-yellow-500/30 rounded-lg p-4 text-yellow-100 text-sm">
          Open your wallet to use quantum messaging.
        </div>
      </div>
    );
  }

  // Unlock screen
  if (!unlocked) {
    return (
      <div className="space-y-6"><Header />
        <div className="bg-gray-700/40 border border-purple-500/30 rounded-lg p-4 text-sm text-gray-300">
          <div className="flex items-center gap-2 mb-2"><Lock className="h-4 w-4 text-purple-400" /><span className="font-medium text-purple-200">End-to-end encrypted</span></div>
          Messages are encrypted with post-quantum keys derived from your recovery phrase. The server only stores ciphertext and never holds your keys.
        </div>
        <Alerts />
        <input
          type="password"
          value={password}
          onChange={(e) => { setPassword(e.target.value); setError(''); }}
          placeholder="Wallet password"
          className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500"
        />
        <div className="flex gap-3">
          <button onClick={() => refresh()} disabled={isLoading || !password}
            className="flex-1 bg-purple-600 hover:bg-purple-700 text-white font-semibold py-3 px-6 rounded-lg transition-colors disabled:opacity-50">
            {isLoading ? 'Unlocking…' : 'Open Inbox'}
          </button>
          <button onClick={handleEnableMessaging} disabled={isLoading || !password}
            className="flex-1 bg-gray-600 hover:bg-gray-700 text-white font-semibold py-3 px-6 rounded-lg transition-colors disabled:opacity-50">
            Enable Messaging
          </button>
        </div>
        <button onClick={handleAnchorOnChain} disabled={isLoading || !password}
          className="w-full bg-gray-700 hover:bg-gray-600 text-purple-200 text-sm py-2 px-4 rounded-lg transition-colors disabled:opacity-50">
          Anchor keys on-chain (trustless · costs a small fee)
        </button>
        <p className="text-xs text-gray-400">First time? Tap “Enable Messaging” to publish your keys to the relay (instant). Optionally “Anchor keys on-chain” so others can discover them without trusting the relay.</p>
      </div>
    );
  }

  // Conversation thread view
  if (selected) {
    return (
      <div className="space-y-4"><Header />
        <div className="flex items-center justify-between">
          <button onClick={() => setSelected(null)} className="text-sm text-purple-300 hover:text-purple-200">← All conversations</button>
          <span className="text-xs text-gray-400 font-mono break-all">{selected}</span>
        </div>
        <Alerts />
        <div className="bg-gray-800 rounded-lg border border-gray-700 p-4 space-y-3 min-h-[240px] max-h-[420px] overflow-y-auto">
          {thread.length === 0 ? (
            <p className="text-gray-500 text-sm text-center py-8">No messages yet.</p>
          ) : thread.map((m) => (
            <div key={m.message_id} className={`flex ${m.mine ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${m.mine ? 'bg-purple-600 text-white' : 'bg-gray-700 text-gray-100'}`}>
                <div className="whitespace-pre-wrap break-words">{m.plaintext}</div>
                <div className="text-[10px] opacity-70 mt-1 flex items-center gap-1">
                  {fmt(m.ts)}{!m.mine && m.verified && <CheckCircle className="h-3 w-3 text-green-300" title="Signature verified" />}
                </div>
              </div>
            </div>
          ))}
        </div>
        <div className="flex gap-2">
          <input
            value={compose.content}
            onChange={(e) => setCompose((c) => ({ ...c, to_address: selected, content: e.target.value }))}
            onKeyPress={(e) => e.key === 'Enter' && handleSend()}
            placeholder="Type an encrypted message…"
            className="flex-1 px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500"
          />
          <button onClick={handleSend} disabled={isLoading || !compose.content}
            className="bg-purple-600 hover:bg-purple-700 text-white px-4 rounded-lg transition-colors disabled:opacity-50 flex items-center gap-1">
            <Send size={18} />
          </button>
        </div>
      </div>
    );
  }

  // Inbox / conversation list
  return (
    <div className="space-y-4"><Header />
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm text-gray-300"><MessageCircle className="h-4 w-4 text-purple-400" /> Inbox</div>
        <div className="flex gap-2">
          <button onClick={() => refresh()} disabled={isLoading} className="text-gray-300 hover:text-white p-2 rounded-lg hover:bg-gray-700 transition-colors" title="Refresh">
            <RefreshCw size={18} className={isLoading ? 'animate-spin' : ''} />
          </button>
          <button onClick={() => { setShowCompose(true); setCompose({ to_address: '', content: '' }); }}
            className="bg-purple-600 hover:bg-purple-700 text-white px-3 py-2 rounded-lg transition-colors flex items-center gap-1 text-sm">
            <Plus size={16} /> New
          </button>
        </div>
      </div>
      <Alerts />

      {showCompose && (
        <div className="bg-gray-800 rounded-lg border border-purple-500/30 p-4 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-purple-200">New encrypted message</span>
            <button onClick={() => setShowCompose(false)} className="text-gray-400 hover:text-white"><X size={18} /></button>
          </div>
          <input
            value={compose.to_address}
            onChange={(e) => setCompose((c) => ({ ...c, to_address: e.target.value }))}
            placeholder="Recipient address (wepo1q…)"
            className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500 font-mono text-sm"
          />
          <textarea
            value={compose.content}
            onChange={(e) => setCompose((c) => ({ ...c, content: e.target.value }))}
            rows={3}
            placeholder="Message (encrypted end-to-end)…"
            className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500"
          />
          <button onClick={handleSend} disabled={isLoading || !compose.to_address || !compose.content}
            className="w-full bg-purple-600 hover:bg-purple-700 text-white font-semibold py-2 rounded-lg transition-colors disabled:opacity-50 flex items-center justify-center gap-2">
            <Send size={18} /> {isLoading ? 'Sending…' : 'Send'}
          </button>
          <p className="text-xs text-gray-400 flex items-center gap-1">
            <AlertTriangle className="h-3 w-3 text-yellow-400" /> The recipient must have enabled messaging (published keys) to receive this.
          </p>
        </div>
      )}

      <div className="bg-gray-800 rounded-lg border border-gray-700 divide-y divide-gray-700">
        {conversations.length === 0 ? (
          <div className="text-center py-10">
            <MessageCircle className="h-10 w-10 text-gray-600 mx-auto mb-2" />
            <p className="text-gray-500 text-sm">No conversations yet. Tap “New” to send an encrypted message.</p>
          </div>
        ) : conversations.map((c) => (
          <button key={c.address} onClick={() => setSelected(c.address)}
            className="w-full text-left p-4 hover:bg-gray-700/50 transition-colors">
            <div className="flex items-center justify-between">
              <span className="text-sm font-mono text-purple-200 break-all">{c.address}</span>
              <span className="text-xs text-gray-500 flex-shrink-0 ml-2">{fmt(c.ts)}</span>
            </div>
            <div className="text-sm text-gray-400 truncate mt-1">{c.last}</div>
          </button>
        ))}
      </div>
    </div>
  );
};

export default QuantumMessaging;
