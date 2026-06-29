import React, { useState, useEffect, useCallback } from 'react';
import {
  ArrowLeft,
  Send,
  Inbox,
  Lock,
  ShieldCheck,
  CheckCircle,
  RefreshCw,
  Eye,
  EyeOff,
} from 'lucide-react';
import { useWallet } from '../contexts/WalletContext';

/**
 * Private messaging — wired to the wallet address. Dead simple: enter a recipient
 * WEPO address, type a message, Send. An Inbox button retrieves all messages.
 *
 * Post-quantum end-to-end encrypted (ML-KEM-768 + AES-256-GCM + ML-DSA-44); all
 * crypto is client-side and the relay only ever stores opaque ciphertext. Once
 * activated, messaging needs no password and is free.
 */
const QuantumMessaging = ({ onBack }) => {
  const {
    wallet,
    sendMessage,
    fetchMessages,
    isMessagingActivated,
    activateMessaging,
    ensureMessagingReady,
  } = useWallet();
  const currentAddress = wallet?.address;

  const [activated, setActivated] = useState(isMessagingActivated());

  // Activation (one-time, only for wallets opened before messaging existed)
  const [activatePw, setActivatePw] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [activating, setActivating] = useState(false);

  // Compose
  const [toAddress, setToAddress] = useState('');
  const [message, setMessage] = useState('');
  const [sending, setSending] = useState(false);

  // Inbox
  const [inbox, setInbox] = useState([]);
  const [loadingInbox, setLoadingInbox] = useState(false);

  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const loadInbox = useCallback(async () => {
    if (!isMessagingActivated()) return;
    setLoadingInbox(true);
    try {
      const msgs = await fetchMessages();
      setInbox(msgs);
    } catch (e) {
      if (e.code !== 'MESSAGING_NOT_ACTIVATED') setError(e.message || 'Failed to load inbox');
    } finally {
      setLoadingInbox(false);
    }
  }, [fetchMessages, isMessagingActivated]);

  // On open: publish our keys (so others can reach us) and pull the inbox once.
  useEffect(() => {
    if (!activated || !currentAddress) return;
    ensureMessagingReady();
    loadInbox();
  }, [activated, currentAddress, ensureMessagingReady, loadInbox]);

  const handleActivate = async () => {
    if (!activatePw) { setError('Enter your wallet password'); return; }
    setActivating(true);
    setError('');
    try {
      await activateMessaging(activatePw);
      setActivatePw('');
      setActivated(true);
      setSuccess('Messaging activated. You won’t need a password for messaging again.');
    } catch (e) {
      setError(e.message || 'Activation failed');
    } finally {
      setActivating(false);
    }
  };

  const handleSend = async () => {
    const to = toAddress.trim();
    const body = message.trim();
    if (!to || !body) { setError('Enter a recipient address and a message'); return; }
    setSending(true);
    setError('');
    setSuccess('');
    try {
      await sendMessage(to, body);
      setSuccess('✅ Message sent (end-to-end encrypted).');
      setMessage('');
    } catch (e) {
      setError(e.message || 'Failed to send message');
    } finally {
      setSending(false);
    }
  };

  const short = (addr) => (addr && addr.length > 20 ? `${addr.slice(0, 12)}…${addr.slice(-8)}` : addr);
  const fmt = (ts) => {
    if (!ts) return '';
    const d = new Date(ts * 1000);
    return d.toLocaleString();
  };

  const Header = () => (
    <div className="flex items-center gap-3 mb-6">
      <button onClick={onBack} className="text-gray-400 hover:text-white transition-colors"><ArrowLeft size={24} /></button>
      <div className="flex items-center gap-2">
        <ShieldCheck className="h-6 w-6 text-purple-400" />
        <h2 className="text-xl font-semibold text-white">Private Messages</h2>
      </div>
    </div>
  );

  const Alerts = () => (
    <>
      {error && <div className="bg-red-900/50 border border-red-500 rounded-lg p-3 text-red-200 text-sm">{error}</div>}
      {success && <div className="bg-green-900/40 border border-green-500 rounded-lg p-3 text-green-200 text-sm">{success}</div>}
    </>
  );

  if (!currentAddress) {
    return (
      <div className="space-y-6"><Header />
        <div className="bg-yellow-900/30 border border-yellow-500/30 rounded-lg p-4 text-yellow-100 text-sm">
          Open your wallet to use private messaging.
        </div>
      </div>
    );
  }

  // One-time activation (only shown for wallets opened before messaging existed).
  if (!activated) {
    return (
      <div className="space-y-6"><Header />
        <div className="bg-gray-700/40 border border-purple-500/30 rounded-lg p-4 text-sm text-gray-300">
          <div className="flex items-center gap-2 mb-2"><Lock className="h-4 w-4 text-purple-400" /><span className="font-medium text-purple-200">Activate messaging (one-time)</span></div>
          Enter your wallet password once to turn on private messaging for this wallet.
          After this you’ll never need a password to message — just type an address and send.
        </div>
        <Alerts />
        <div className="relative">
          <input
            type={showPw ? 'text' : 'password'}
            value={activatePw}
            onChange={(e) => { setActivatePw(e.target.value); setError(''); }}
            onKeyDown={(e) => e.key === 'Enter' && handleActivate()}
            placeholder="Wallet password"
            className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500 pr-12"
          />
          <button type="button" onClick={() => setShowPw(!showPw)} className="absolute right-3 top-3 text-gray-400 hover:text-purple-400">
            {showPw ? <EyeOff size={20} /> : <Eye size={20} />}
          </button>
        </div>
        <button onClick={handleActivate} disabled={activating || !activatePw}
          className="w-full bg-purple-600 hover:bg-purple-700 text-white font-semibold py-3 px-6 rounded-lg transition-colors disabled:opacity-50">
          {activating ? 'Activating…' : 'Activate messaging'}
        </button>
      </div>
    );
  }

  // Main: simple send form + inbox.
  return (
    <div className="space-y-6"><Header />

      <div className="bg-gray-700/40 border border-purple-500/30 rounded-lg p-3 text-xs text-gray-300 flex items-center gap-2">
        <Lock className="h-4 w-4 text-purple-400 flex-shrink-0" />
        Post-quantum end-to-end encrypted · free · no password needed
      </div>

      <Alerts />

      {/* Compose */}
      <div className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-purple-200 mb-2">Recipient Address</label>
          <input
            type="text"
            value={toAddress}
            onChange={(e) => { setToAddress(e.target.value); setError(''); }}
            placeholder="wepo1q…"
            className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500 font-mono text-sm"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-purple-200 mb-2">Message</label>
          <textarea
            value={message}
            onChange={(e) => { setMessage(e.target.value); setError(''); }}
            rows={4}
            placeholder="Type your encrypted message…"
            className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500"
          />
        </div>
        <button onClick={handleSend} disabled={sending || !toAddress.trim() || !message.trim()}
          className="w-full bg-purple-600 hover:bg-purple-700 text-white font-semibold py-3 px-6 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2">
          <Send size={20} /> {sending ? 'Sending…' : 'Send Message'}
        </button>
      </div>

      {/* Inbox */}
      <div className="pt-2">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2 text-sm font-medium text-purple-200">
            <Inbox className="h-4 w-4 text-purple-400" /> Inbox {inbox.length > 0 && <span className="text-gray-400">({inbox.length})</span>}
          </div>
          <button onClick={loadInbox} disabled={loadingInbox}
            className="bg-gray-700 hover:bg-gray-600 text-white text-sm px-3 py-2 rounded-lg transition-colors flex items-center gap-2 disabled:opacity-50">
            <RefreshCw size={16} className={loadingInbox ? 'animate-spin' : ''} /> {loadingInbox ? 'Loading…' : 'Get Messages'}
          </button>
        </div>

        <div className="bg-gray-800 rounded-lg border border-gray-700 divide-y divide-gray-700">
          {inbox.length === 0 ? (
            <div className="text-center py-10 text-gray-500 text-sm">
              {loadingInbox ? 'Loading messages…' : 'No messages. Tap “Get Messages” to check your inbox.'}
            </div>
          ) : inbox.map((m) => (
            <div key={m.message_id} className="p-4">
              <div className="flex items-center justify-between gap-2 mb-1">
                <span className="text-xs font-mono text-purple-200 break-all">{short(m.from)}</span>
                <span className="text-xs text-gray-500 flex-shrink-0 flex items-center gap-1">
                  {m.verified && <CheckCircle className="h-3 w-3 text-green-400" title="Signature verified" />}
                  {fmt(m.ts)}
                </span>
              </div>
              <div className="text-sm text-gray-100 whitespace-pre-wrap break-words">{m.plaintext}</div>
              <button
                onClick={() => { setToAddress(m.from); window.scrollTo({ top: 0, behavior: 'smooth' }); }}
                className="text-xs text-purple-300 hover:text-purple-200 mt-2"
              >
                Reply
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default QuantumMessaging;
