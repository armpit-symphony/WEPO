import React, { useState, useEffect } from 'react';
import { 
  ArrowLeft, 
  Send, 
  Users, 
  MessageCircle, 
  Shield, 
  Key,
  Lock,
  Plus,
  X,
  AlertTriangle,
  Zap,
  CheckCircle,
  User,
  AlertCircle
} from 'lucide-react';
import { useWallet } from '../contexts/WalletContext';
// Temporarily commented out for Buffer isolation testing
// import { validateWepoAddress } from '../utils/addressUtils';

const QuantumMessaging = ({ onBack }) => {
  const { wallet } = useWallet();
  
  const [activeTab, setActiveTab] = useState('inbox');
  const [conversations, setConversations] = useState([]);
  const [selectedConversation, setSelectedConversation] = useState(null);
  const [conversationMessages, setConversationMessages] = useState([]);
  const [newMessage, setNewMessage] = useState({
    to_address: '',
    subject: '',
    content: ''
  });
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [showNewMessage, setShowNewMessage] = useState(false);
  const [messagingStats, setMessagingStats] = useState(null);

  const backendUrl = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8001';
  const currentWallet = wallet;
  const currentAddress = currentWallet?.address;

  useEffect(() => {
    if (currentAddress) {
      loadInboxMessages();
      loadMessagingStats();
    }
  }, [currentAddress]);

  const loadInboxMessages = async () => {
    if (!currentAddress) return;
    
    setIsLoading(true);
    try {
      const response = await fetch(`${backendUrl}/api/messaging/inbox/${currentAddress}`);
      if (response.ok) {
        const data = await response.json();

        // Extract unique conversations
        const uniqueConversations = new Map();
        data.messages?.forEach(msg => {
          const otherAddress = msg.from_address === currentAddress ? msg.to_address : msg.from_address;
          if (!uniqueConversations.has(otherAddress) || 
              uniqueConversations.get(otherAddress).timestamp < msg.timestamp) {
            uniqueConversations.set(otherAddress, {
              address: otherAddress,
              lastMessage: msg.content.substring(0, 50) + '...',
              timestamp: msg.timestamp,
              unread: !msg.read_status && msg.to_address === currentAddress
            });
          }
        });
        
        setConversations(Array.from(uniqueConversations.values()));
      }
    } catch (error) {
      console.error('Failed to load messages:', error);
      setError('Failed to load messages');
    } finally {
      setIsLoading(false);
    }
  };

  const loadMessagingStats = async () => {
    try {
      const response = await fetch(`${backendUrl}/api/messaging/stats`);
      if (response.ok) {
        const data = await response.json();
        setMessagingStats(data.stats);
      }
    } catch (error) {
      console.error('Failed to load messaging stats:', error);
    }
  };

  const loadConversation = async (otherAddress) => {
    if (!currentAddress) return;
    
    setIsLoading(true);
    try {
      const response = await fetch(`${backendUrl}/api/messaging/conversation/${currentAddress}/${otherAddress}`);
      if (response.ok) {
        const data = await response.json();
        setConversationMessages(data.conversation || []);
        setSelectedConversation(otherAddress);
        setActiveTab('conversation');
      }
    } catch (error) {
      console.error('Failed to load conversation:', error);
      setError('Failed to load conversation');
    } finally {
      setIsLoading(false);
    }
  };

  const sendMessage = async () => {
    if (!currentAddress || !newMessage.to_address || !newMessage.content) {
      setError('Please fill in all required fields');
      return;
    }

    setIsLoading(true);
    try {
      const response = await fetch(`${backendUrl}/api/messaging/send`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          from_address: currentAddress,
          to_address: newMessage.to_address,
          content: newMessage.content,
          subject: newMessage.subject || 'No Subject',
          message_type: 'text'
        })
      });

      if (response.ok) {
        const data = await response.json();
        setNewMessage({ to_address: '', subject: '', content: '' });
        setShowNewMessage(false);
        setError('');
        
        // Refresh messages
        await loadInboxMessages();
        
        // If we're in a conversation with this address, refresh it
        if (selectedConversation === newMessage.to_address) {
          await loadConversation(newMessage.to_address);
        }
      } else {
        const errorData = await response.json();
        setError(errorData.detail || 'Failed to send message');
      }
    } catch (error) {
      console.error('Failed to send message:', error);
      setError('Failed to send message');
    } finally {
      setIsLoading(false);
    }
  };

  const formatTimestamp = (timestamp) => {
    const date = new Date(timestamp * 1000);
    const now = new Date();
    const diffHours = (now - date) / (1000 * 60 * 60);
    
    if (diffHours < 1) {
      return 'Just now';
    } else if (diffHours < 24) {
      return `${Math.floor(diffHours)}h ago`;
    } else {
      return date.toLocaleDateString();
    }
  };

  const validateAddress = (address) => {
    // Temporarily disabled for Buffer isolation testing
    return address && address.length > 10; // Basic validation
  };

  if (activeTab === 'conversation' && selectedConversation) {
    return (
      <div className="h-full flex flex-col bg-gray-900">
        {/* Conversation Header */}
        <div className="bg-gray-800 border-b border-purple-500/30 p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <button
                onClick={() => {
                  setActiveTab('inbox');
                  setSelectedConversation(null);
                }}
                className="text-gray-400 hover:text-white"
              >
                <ArrowLeft size={20} />
              </button>
              <div className="flex items-center gap-2">
                <Shield className="h-5 w-5 text-purple-400" />
                <div>
                  <h3 className="text-white font-medium">
                    {selectedConversation.substring(0, 20)}...
                  </h3>
                  <p className="text-xs text-gray-400">Experimental messaging preview</p>
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2 bg-green-900/20 px-3 py-1 rounded-full">
              <Zap className="h-3 w-3 text-green-400" />
              <span className="text-xs text-green-400">Preview</span>
            </div>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {conversationMessages.map((msg) => (
            <div
              key={msg.message_id}
              className={`flex ${msg.from_address === currentAddress ? 'justify-end' : 'justify-start'}`}
            >
              <div
                className={`max-w-xs lg:max-w-md px-4 py-2 rounded-lg ${
                  msg.from_address === currentAddress
                    ? 'bg-purple-600 text-white'
                    : 'bg-gray-700 text-gray-100'
                }`}
              >
                <p className="text-sm">{msg.content}</p>
                <div className="flex items-center justify-between mt-1">
                  <span className="text-xs opacity-70">
                    {formatTimestamp(msg.timestamp)}
                  </span>
                  {msg.signature_valid && (
                    <CheckCircle className="h-3 w-3 text-green-400" />
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Message Input */}
        <div className="bg-gray-800 border-t border-purple-500/30 p-4">
          <div className="flex items-center gap-3">
            <input
              type="text"
              value={newMessage.content}
              onChange={(e) => setNewMessage(prev => ({ 
                ...prev, 
                content: e.target.value,
                to_address: selectedConversation 
              }))}
              placeholder="Type a message..."
              className="flex-1 bg-gray-700 border border-gray-600 rounded-lg px-4 py-2 text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500"
              onKeyPress={(e) => e.key === 'Enter' && sendMessage()}
            />
            <button
              onClick={sendMessage}
              disabled={!newMessage.content || isLoading}
              className="bg-purple-600 hover:bg-purple-700 disabled:bg-gray-600 text-white p-2 rounded-lg transition-colors"
            >
              <Send size={20} />
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full bg-gray-900 text-white">
      {/* Header */}
      <div className="bg-gray-800 border-b border-purple-500/30 p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={onBack}
              className="text-gray-400 hover:text-white"
            >
              <ArrowLeft size={20} />
            </button>
            <div className="flex items-center gap-2">
              <MessageCircle className="h-6 w-6 text-purple-400" />
              <div>
                <h2 className="text-xl font-bold">Quantum Messages</h2>
                <p className="text-sm text-gray-400">Experimental public-test messaging preview</p>
              </div>
            </div>
          </div>
          
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 bg-purple-900/30 px-3 py-1 rounded-full">
              <Zap className="h-4 w-4 text-yellow-400" />
              <span className="text-sm text-yellow-400">Experimental</span>
            </div>
            <button
              onClick={() => setShowNewMessage(true)}
              className="bg-purple-600 hover:bg-purple-700 text-white px-4 py-2 rounded-lg flex items-center gap-2"
            >
              <Plus size={16} />
              New Message
            </button>
          </div>
        </div>
      </div>

      <div className="bg-blue-900/30 border-b border-blue-500/20 p-4">
        <div className="flex items-start gap-2">
          <AlertTriangle className="h-4 w-4 text-blue-300 mt-0.5" />
          <p className="text-sm text-gray-300">
            Messaging endpoints are available on the public-test backend, but this web UI has not had the same broader validation pass as the main wallet flow. Treat this screen as an experimental preview rather than a finished secure messaging product.
          </p>
        </div>
      </div>

      {/* Stats Bar */}
      {messagingStats && (
        <div className="bg-gray-800/50 border-b border-purple-500/20 p-3">
          <div className="grid grid-cols-4 gap-4 text-center">
            <div>
              <div className="text-lg font-bold text-purple-400">{messagingStats.total_messages}</div>
              <div className="text-xs text-gray-400">Messages</div>
            </div>
            <div>
              <div className="text-lg font-bold text-blue-400">{messagingStats.total_threads}</div>
              <div className="text-xs text-gray-400">Threads</div>
            </div>
            <div>
              <div className="text-lg font-bold text-green-400">{messagingStats.total_users}</div>
              <div className="text-xs text-gray-400">Users</div>
            </div>
            <div>
              <div className="text-lg font-bold text-yellow-400">{messagingStats.messages_today}</div>
              <div className="text-xs text-gray-400">Today</div>
            </div>
          </div>
        </div>
      )}

      {/* Error Display */}
      {error && (
        <div className="bg-red-900/20 border border-red-500/30 rounded-lg p-3 m-4">
          <div className="flex items-center gap-2">
            <AlertCircle className="h-4 w-4 text-red-400" />
            <p className="text-red-300 text-sm">{error}</p>
          </div>
        </div>
      )}

      {/* New Message Modal */}
      {showNewMessage && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-gray-800 rounded-xl p-6 w-full max-w-md mx-4">
            <h3 className="text-xl font-bold mb-4">New Message</h3>
            
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2">
                  To Address
                </label>
                <input
                  type="text"
                  value={newMessage.to_address}
                  onChange={(e) => setNewMessage(prev => ({ ...prev, to_address: e.target.value }))}
                  placeholder="wepo1..."
                  className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2 text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500"
                />
                {newMessage.to_address && !validateAddress(newMessage.to_address) && (
                  <p className="text-red-400 text-xs mt-1">Invalid WEPO address format</p>
                )}
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2">
                  Subject (Optional)
                </label>
                <input
                  type="text"
                  value={newMessage.subject}
                  onChange={(e) => setNewMessage(prev => ({ ...prev, subject: e.target.value }))}
                  placeholder="Message subject"
                  className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2 text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500"
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2">
                  Message
                </label>
                <textarea
                  value={newMessage.content}
                  onChange={(e) => setNewMessage(prev => ({ ...prev, content: e.target.value }))}
                  placeholder="Your message..."
                  rows={4}
                  className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2 text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500"
                />
              </div>
            </div>
            
            <div className="flex items-center justify-between mt-6">
              <button
                onClick={() => {
                  setShowNewMessage(false);
                  setNewMessage({ to_address: '', subject: '', content: '' });
                  setError('');
                }}
                className="px-4 py-2 text-gray-400 hover:text-white transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={sendMessage}
                disabled={!newMessage.to_address || !newMessage.content || !validateAddress(newMessage.to_address) || isLoading}
                className="bg-purple-600 hover:bg-purple-700 disabled:bg-gray-600 text-white px-6 py-2 rounded-lg transition-colors flex items-center gap-2"
              >
                {isLoading ? (
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                ) : (
                  <Send size={16} />
                )}
                Send Message
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Main Content */}
      <div className="flex-1 overflow-hidden">
        {/* Conversations List */}
        <div className="h-full overflow-y-auto">
          {isLoading ? (
            <div className="flex items-center justify-center h-64">
              <div className="w-8 h-8 border-4 border-purple-500 border-t-transparent rounded-full animate-spin"></div>
            </div>
          ) : conversations.length === 0 ? (
            <div className="text-center py-12">
              <MessageCircle className="h-16 w-16 text-gray-500 mx-auto mb-4" />
              <h3 className="text-xl font-medium text-gray-300 mb-2">No Messages Yet</h3>
              <p className="text-gray-500 mb-4">Start a messaging preview conversation</p>
              <button
                onClick={() => setShowNewMessage(true)}
                className="bg-purple-600 hover:bg-purple-700 text-white px-6 py-2 rounded-lg"
              >
                Send First Message
              </button>
            </div>
          ) : (
            <div className="divide-y divide-gray-700">
              {conversations.map((conversation) => (
                <div
                  key={conversation.address}
                  onClick={() => loadConversation(conversation.address)}
                  className="p-4 hover:bg-gray-800 cursor-pointer transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 bg-purple-600 rounded-full flex items-center justify-center">
                        <User size={20} />
                      </div>
                      <div>
                        <h4 className="font-medium text-white">
                          {conversation.address.substring(0, 20)}...
                        </h4>
                        <p className="text-sm text-gray-400 truncate max-w-xs">
                          {conversation.lastMessage}
                        </p>
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="text-xs text-gray-500 mb-1">
                        {formatTimestamp(conversation.timestamp)}
                      </div>
                      <div className="flex items-center gap-1">
                        <Shield className="h-3 w-3 text-green-400" />
                        {conversation.unread && (
                          <div className="w-2 h-2 bg-purple-500 rounded-full"></div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default QuantumMessaging;
