import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  ArrowLeft,
  Send,
  MessageCircle,
  Lock,
  Plus,
  X,
  CheckCircle,
  ShieldCheck,
} from 'lucide-react';
import { useWallet } from '../contexts/WalletContext';

/**
 * Quantum private messaging — a texting-style chat. Post-quantum end-to-end
 * (ML-KEM-768 + AES-256-GCM + ML-DSA-44), all crypto client-side; the relay only
 * ever stores opaque ciphertext.
 *
 * No password, no "enable" step: messaging is live whenever the wallet is open
 * (keys are derived/published automatically by WalletContext) and sending is free.
 */
const QuantumMessaging = ({ onBack }) => {
  const { wallet, sendMessage, fetchMessages } = useWallet();
  const currentAddress = wallet?.address;

  const [messages, setMessages] = useState([]);   // decrypted received messages
  const [sentLog, setSentLog] = useState([]);      // local echo of sent messages
  const [selected, setSelected] = useState(null);  // open conversation address
  const [draft, setDraft] = useState('');          // thread composer text
  const [showNew, setShowNew] = useState(false);
  const [newTo, setNewTo] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');

  const threadEndRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const inbox = await fetchMessages();
      setMessages(inbox);
    } catch (e) {
      // Quietly tolerate transient relay/network errors during polling.
    }
  }, [fetchMessages]);

  // Initial load + light polling so new messages arrive without a refresh button.
  useEffect(() => {
    if (!currentAddress) return;
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, [currentAddress, load]);

  const short = (addr) => (addr && addr.length > 16 ? `${addr.slice(0, 10)}…${addr.slice(-6)}` : addr);
  const fmt = (ts) => {
    if (!ts) return '';
    const d = new Date(ts * 1000);
    const h = (Date.now() - d.getTime()) / 36e5;
    if (h < 0.0167) return 'now';
    if (h < 1) return `${Math.floor(h * 60)}m`;
    if (h < 24) return `${Math.floor(h)}h`;
    return d.toLocaleDateString();
  };

  // Conversations grouped by the other party's address.
  const conversations = (() => {
    const map = new Map();
    const add = (addr, item) => {
      if (!addr) return;
      const cur = map.get(addr);
      if (!cur || (cur.ts || 0) <= (item.ts || 0)) {
        map.set(addr, { address: addr, last: item.plaintext, ts: item.ts });
      }
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

  // Keep the thread pinned to the latest message.
  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [selected, messages, sentLog]);

  const handleSend = async () => {
    const to = selected;
    const content = draft.trim();
    if (!to || !content || sending) return;
    setSending(true);
    setError('');
    try {
      await sendMessage(to, content);
      setSentLog((prev) => [...prev, {
        message_id: `local-${Date.now()}`,
        to,
        plaintext: content,
        ts: Math.floor(Date.now() / 1000),
        mine: true,
      }]);
      setDraft('');
    } catch (e) {
      setError(e.message || 'Failed to send message');
    } finally {
      setSending(false);
    }
  };

  const startNewChat = () => {
    const to = newTo.trim();
    if (!to) return;
    setSelected(to);
    setShowNew(false);
    setNewTo('');
    setError('');
  };

  const Header = ({ title, onBackClick, subtitle }) => (
    <div className="flex items-center gap-3 mb-4">
      <button onClick={onBackClick} className="text-gray-400 hover:text-white transition-colors">
        <ArrowLeft size={24} />
      </button>
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-5 w-5 text-purple-400 flex-shrink-0" />
          <h2 className="text-lg font-semibold text-white truncate">{title}</h2>
        </div>
        {subtitle && <p className="text-xs text-gray-400 font-mono truncate">{subtitle}</p>}
      </div>
    </div>
  );

  if (!currentAddress) {
    return (
      <div className="space-y-4">
        <Header title="Messages" onBackClick={onBack} />
        <div className="bg-yellow-900/30 border border-yellow-500/30 rounded-lg p-4 text-yellow-100 text-sm">
          Open your wallet to use private messaging.
        </div>
      </div>
    );
  }

  // ---- Conversation thread (texting view) ----
  if (selected) {
    return (
      <div className="flex flex-col h-[70vh] min-h-[420px]">
        <Header title={short(selected)} subtitle={selected} onBackClick={() => { setSelected(null); setError(''); }} />

        <div className="flex-1 overflow-y-auto bg-gray-900/40 rounded-lg border border-gray-700 p-3 space-y-2">
          {thread.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center text-gray-500">
              <Lock className="h-8 w-8 mb-2 text-gray-600" />
              <p className="text-sm">No messages yet — say hello.</p>
              <p className="text-xs mt-1">End-to-end encrypted.</p>
            </div>
          ) : thread.map((m) => (
            <div key={m.message_id} className={`flex ${m.mine ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[78%] rounded-2xl px-3.5 py-2 text-sm ${m.mine
                ? 'bg-purple-600 text-white rounded-br-md'
                : 'bg-gray-700 text-gray-100 rounded-bl-md'}`}>
                <div className="whitespace-pre-wrap break-words">{m.plaintext}</div>
                <div className={`text-[10px] mt-1 flex items-center gap-1 ${m.mine ? 'text-purple-200' : 'text-gray-400'}`}>
                  {fmt(m.ts)}
                  {!m.mine && m.verified && <CheckCircle className="h-3 w-3 text-green-300" title="Signature verified" />}
                </div>
              </div>
            </div>
          ))}
          <div ref={threadEndRef} />
        </div>

        {error && <div className="text-red-300 text-xs mt-2">{error}</div>}

        <div className="flex items-end gap-2 mt-3">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
            rows={1}
            placeholder="Message"
            className="flex-1 resize-none px-4 py-3 bg-gray-700 border border-gray-600 rounded-2xl text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500 max-h-32"
          />
          <button
            onClick={handleSend}
            disabled={sending || !draft.trim()}
            className="bg-purple-600 hover:bg-purple-700 text-white h-12 w-12 flex-shrink-0 rounded-full flex items-center justify-center transition-colors disabled:opacity-40"
            title="Send (encrypted)"
          >
            <Send size={18} />
          </button>
        </div>
        <p className="text-[10px] text-gray-500 mt-1.5 flex items-center gap-1">
          <Lock className="h-3 w-3" /> Post-quantum end-to-end encrypted · free
        </p>
      </div>
    );
  }

  // ---- Conversation list ----
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <Header title="Messages" subtitle={short(currentAddress)} onBackClick={onBack} />
        <button
          onClick={() => { setShowNew(true); setNewTo(''); setError(''); }}
          className="bg-purple-600 hover:bg-purple-700 text-white px-3 py-2 rounded-full transition-colors flex items-center gap-1 text-sm flex-shrink-0"
        >
          <Plus size={16} /> New
        </button>
      </div>

      {error && <div className="bg-red-900/40 border border-red-500/40 rounded-lg p-3 text-red-200 text-sm">{error}</div>}

      {showNew && (
        <div className="bg-gray-800 rounded-lg border border-purple-500/30 p-4 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-purple-200">New conversation</span>
            <button onClick={() => setShowNew(false)} className="text-gray-400 hover:text-white"><X size={18} /></button>
          </div>
          <input
            value={newTo}
            onChange={(e) => setNewTo(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && startNewChat()}
            placeholder="Recipient address (wepo1q…)"
            className="w-full px-4 py-2.5 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500 font-mono text-sm"
          />
          <button
            onClick={startNewChat}
            disabled={!newTo.trim()}
            className="w-full bg-purple-600 hover:bg-purple-700 text-white font-semibold py-2.5 rounded-lg transition-colors disabled:opacity-40"
          >
            Start chat
          </button>
        </div>
      )}

      <div className="bg-gray-800 rounded-lg border border-gray-700 divide-y divide-gray-700 overflow-hidden">
        {conversations.length === 0 ? (
          <div className="text-center py-12">
            <MessageCircle className="h-10 w-10 text-gray-600 mx-auto mb-2" />
            <p className="text-gray-500 text-sm">No conversations yet.</p>
            <p className="text-gray-600 text-xs mt-1">Tap “New” to send an encrypted message.</p>
          </div>
        ) : conversations.map((c) => (
          <button
            key={c.address}
            onClick={() => { setSelected(c.address); setError(''); }}
            className="w-full text-left p-4 hover:bg-gray-700/50 transition-colors flex items-center gap-3"
          >
            <div className="h-10 w-10 rounded-full bg-purple-600/30 border border-purple-500/40 flex items-center justify-center flex-shrink-0">
              <MessageCircle className="h-5 w-5 text-purple-300" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-mono text-purple-200 truncate">{short(c.address)}</span>
                <span className="text-xs text-gray-500 flex-shrink-0">{fmt(c.ts)}</span>
              </div>
              <div className="text-sm text-gray-400 truncate mt-0.5">{c.last}</div>
            </div>
          </button>
        ))}
      </div>

      <p className="text-[11px] text-gray-500 flex items-center justify-center gap-1.5">
        <Lock className="h-3 w-3" /> Post-quantum end-to-end encrypted · always on while your wallet is open · free
      </p>
    </div>
  );
};

export default QuantumMessaging;
