import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Sparkles, MessageSquare, Plus, Trash2, Send, ShoppingBag, 
  X, Menu, ChevronRight, AlertCircle, ShoppingCart, Info, Check, ChevronDown,
  Activity 
} from 'lucide-react';
import { useChatStore } from './store/chatStore';
import { 
  SuggestedPrompts, ProductCard, ComparisonView, BundleView, SearchContextBadge, SkeletonLoader, formatMessageText,
  ComparisonPreviewCard 
} from './components/ChatComponents';

function App() {
  const {
    conversations,
    activeConversationId,
    cart,
    loading,
    setActiveConversation,
    createNewChat,
    deleteConversation,
    sendMessage,
    addToCart,
    removeFromCart,
    updateCartQuantity,
    clearCart
  } = useChatStore();

  const [input, setInput] = useState('');
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [isCartOpen, setIsCartOpen] = useState(false);
  const [checkoutSuccess, setCheckoutSuccess] = useState(false);
  const [comparedProducts, setComparedProducts] = useState([]);
  const [activeComparison, setActiveComparison] = useState(null);
  const paginationLoading = useChatStore(state => state.paginationLoading);
  const loadMore = useChatStore(state => state.loadMore);
  
  const chatEndRef = useRef(null);

  // Retrieve active conversation object
  const activeConversation = conversations.find(c => c.id === activeConversationId);

  // Automatically scroll to bottom of chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [activeConversation?.messages, loading]);

  // Adjust sidebar on mobile sizing
  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth < 768) {
        setIsSidebarOpen(false);
      } else {
        setIsSidebarOpen(true);
      }
    };
    
    window.addEventListener('resize', handleResize);
    // Initial call
    handleResize();
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // Ensure a fresh new chat on startup if the last active chat has history.
  // This satisfies the requirement to start a fresh chat when the server/app is started,
  // while keeping the previous chat saved in the sidebar history.
  useEffect(() => {
    if (activeConversation && activeConversation.messages.length > 1) {
      createNewChat();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Set up Server-Sent Events (SSE) stream for real-time product discovery
  useEffect(() => {
    if (activeConversationId) {
      useChatStore.getState().setupStream(activeConversationId);
    }
    return () => {
      useChatStore.getState().setupStream(null);
    };
  }, [activeConversationId]);

  // Automatically open new comparison drawer when it arrives in the chat
  useEffect(() => {
    if (activeConversation && activeConversation.messages.length > 0) {
      const lastMessage = activeConversation.messages[activeConversation.messages.length - 1];
      if (lastMessage && lastMessage.role === 'assistant') {
        if (lastMessage.comparison) {
          setActiveComparison(lastMessage.comparison);
        } else if (lastMessage.comparisonTable) {
          setActiveComparison(lastMessage.comparisonTable);
        }
      }
    }
  }, [activeConversation?.messages]);

  const handleSend = async (textToSend) => {
    const messageText = textToSend || input;
    if (!messageText.trim()) return;

    setInput('');
    // Clear product comparisons on new manual search query
    setComparedProducts([]);
    await sendMessage(messageText);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // Handles adding/removing products from compared item state
  const handleCompareToggle = (product) => {
    setComparedProducts((prev) => {
      const exists = prev.find(p => p.id === product.id);
      if (exists) {
        return prev.filter(p => p.id !== product.id);
      }
      if (prev.length >= 2) {
        // Swap second item out to cap at 2
        return [prev[0], product];
      }
      return [...prev, product];
    });
  };

  // Triggers manual side-by-side comparison command based on checkboxes
  const handleTriggerComparison = () => {
    if (comparedProducts.length < 2) return;
    const commandText = `Compare ${comparedProducts[0].name} and ${comparedProducts[1].name}`;
    handleSend(commandText);
  };

  // Calculate cart subtotal
  const cartSubtotal = cart.reduce((sum, item) => sum + (item.price * item.quantity), 0);

  const handleCheckout = () => {
    setCheckoutSuccess(true);
    setTimeout(() => {
      clearCart();
      setCheckoutSuccess(false);
      setIsCartOpen(false);
    }, 2500);
  };

  // Check if active chat has user content (if only welcome assistant msg, it is empty state)
  const isChatEmpty = !activeConversation || activeConversation.messages.length <= 1;

  return (
    <div className="relative flex h-screen w-screen bg-slate-900 text-slate-100 overflow-hidden font-sans">
      
      {/* Background glowing mesh lights */}
      <div className="bg-mesh -top-40 -left-40"></div>
      <div className="bg-mesh -bottom-40 -right-40"></div>

      {/* 1. SIDEBAR HISTORY PANEL */}
      <AnimatePresence mode="wait">
        {isSidebarOpen && (
          <motion.aside
            initial={{ width: 0, opacity: 0 }}
            animate={{ width: 280, opacity: 1 }}
            exit={{ width: 0, opacity: 0 }}
            transition={{ duration: 0.3, ease: 'easeInOut' }}
            className="relative flex flex-col h-full bg-slate-950/60 backdrop-blur-xl border-r border-slate-800/80 z-20 shrink-0"
          >
            {/* Sidebar Header */}
            <div className="p-4 border-b border-slate-800/80 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-xl bg-indigo-500/10 border border-brand-500/30 flex items-center justify-center">
                  <Sparkles className="w-4.5 h-4.5 text-brand-400" />
                </div>
                <span className="font-bold text-white tracking-wide text-sm">SmartAssociate</span>
              </div>
              <button 
                onClick={() => setIsSidebarOpen(false)}
                className="md:hidden p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800/40 cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Create New Chat Button */}
            <div className="p-3">
              <button
                onClick={createNewChat}
                className="w-full py-2.5 px-4 rounded-xl bg-gradient-to-r from-brand-600 to-indigo-600 hover:from-brand-500 hover:to-indigo-500 text-white text-xs font-semibold flex items-center justify-center gap-2 cursor-pointer shadow-lg shadow-indigo-950/40 border border-brand-400/20 hover:scale-[1.01] active:scale-[0.99] transition-all"
              >
                <Plus className="w-4 h-4" />
                <span>New Consultation</span>
              </button>
            </div>

            {/* Conversation History List */}
            <div className="flex-grow overflow-y-auto px-2 space-y-1 py-2">
              <div className="px-2 pb-2 text-[10px] uppercase font-bold text-slate-500 tracking-wider">
                Recent Chats
              </div>
              
              {conversations.length === 0 ? (
                <div className="text-center text-xs text-slate-600 py-8">
                  No conversations yet.
                </div>
              ) : (
                conversations.map((chat) => {
                  const isActive = chat.id === activeConversationId;
                  return (
                    <div
                      key={chat.id}
                      className={`group relative flex items-center rounded-xl transition-all duration-300 mb-1.5 ${
                        isActive 
                          ? 'bg-indigo-500/15 border border-indigo-400/40 text-white font-semibold shadow-[0_0_20px_rgba(99,102,241,0.15)]' 
                          : 'border border-transparent hover:bg-slate-800/45 text-slate-400 hover:text-slate-200 hover:border-slate-700/50'
                      }`}
                    >
                      <button
                        onClick={() => setActiveConversation(chat.id)}
                        className="flex-grow text-left p-3 pr-10 text-xs truncate cursor-pointer flex items-center gap-2"
                      >
                        <MessageSquare className={`w-3.5 h-3.5 ${isActive ? 'text-brand-400' : 'text-slate-500'}`} />
                        <span className="truncate">{chat.title}</span>
                      </button>

                      {/* Delete Conversation Button */}
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          deleteConversation(chat.id);
                        }}
                        className="absolute right-2 opacity-0 group-hover:opacity-100 p-1.5 rounded-lg text-slate-500 hover:text-rose-400 hover:bg-slate-900 cursor-pointer transition-opacity"
                        title="Delete chat"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  );
                })
              )}
            </div>

            {/* Sidebar Footer (Cart indicator) */}
            <div className="p-3 border-t border-slate-800/80 bg-slate-950/40">
              <button
                onClick={() => setIsCartOpen(true)}
                className="w-full p-3 rounded-xl bg-slate-900 border border-slate-800/80 hover:border-brand-500/30 flex items-center justify-between group cursor-pointer transition-all"
              >
                <div className="flex items-center gap-2.5">
                  <div className="relative w-8 h-8 rounded-lg bg-brand-500/10 flex items-center justify-center group-hover:bg-brand-500/20 transition-colors">
                    <ShoppingBag className="w-4 h-4 text-brand-400" />
                    {cart.length > 0 && (
                      <span className="absolute -top-1.5 -right-1.5 bg-brand-500 text-white text-[9px] font-bold w-4 h-4 rounded-full flex items-center justify-center animate-pulse">
                        {cart.reduce((sum, item) => sum + item.quantity, 0)}
                      </span>
                    )}
                  </div>
                  <div className="flex flex-col text-left">
                    <span className="text-[11px] font-bold text-slate-400 group-hover:text-slate-200 transition-colors">Cart Subtotal</span>
                    <span className="text-xs font-semibold text-white">₹{cartSubtotal.toLocaleString('en-IN')}</span>
                  </div>
                </div>
                <ChevronRight className="w-4 h-4 text-slate-500 group-hover:text-slate-300 transition-transform group-hover:translate-x-0.5" />
              </button>
            </div>
          </motion.aside>
        )}
      </AnimatePresence>

      {/* 2. MAIN APPLICATION INTERFACE */}
      <main className="flex-grow flex flex-col h-full min-w-0 z-10">
        
        {/* Main Header bar */}
        <header className="h-16 border-b border-slate-800/60 flex items-center justify-between px-4 bg-slate-900/50 backdrop-blur-md">
          <div className="flex items-center gap-3">
            {/* Toggle sidebar (burger) */}
            {!isSidebarOpen && (
              <button
                onClick={() => setIsSidebarOpen(true)}
                className="p-2 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800/60 border border-slate-800/80 cursor-pointer"
              >
                <Menu className="w-4.5 h-4.5" />
              </button>
            )}
            
            <div className="flex flex-col">
              <div className="flex items-center gap-1.5">
                <h2 className="font-bold text-white text-sm">Virtual Sales Associate</h2>
                <div className="w-2 h-2 rounded-full bg-emerald-500 shadow-[0_0_8px_#10B981]"></div>
              </div>
              <span className="text-[10px] text-slate-400">Powered by local recommendation model</span>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* Desktop Cart Float */}
            {!isSidebarOpen && (
              <button
                onClick={() => setIsCartOpen(true)}
                className="relative p-2 rounded-xl bg-slate-800/60 border border-slate-700/50 text-slate-300 hover:text-white cursor-pointer transition-colors"
              >
                <ShoppingCart className="w-4.5 h-4.5" />
                {cart.length > 0 && (
                  <span className="absolute -top-1 -right-1 bg-brand-500 text-white text-[9px] font-bold w-4 h-4 rounded-full flex items-center justify-center">
                    {cart.reduce((sum, item) => sum + item.quantity, 0)}
                  </span>
                )}
              </button>
            )}
          </div>
        </header>

        {/* Floating Compare Drawer trigger when items selected */}
        <AnimatePresence>
          {comparedProducts.length > 0 && (
            <motion.div 
              initial={{ y: 50, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              exit={{ y: 50, opacity: 0 }}
              className="fixed bottom-24 left-1/2 -translate-x-1/2 z-30 bg-slate-950/90 border border-indigo-500/40 rounded-xl px-4 py-3 shadow-xl backdrop-blur flex items-center gap-4"
            >
              <div className="text-xs">
                <span className="text-slate-400 mr-2">Compare Setup:</span>
                <span className="text-brand-300 font-semibold">{comparedProducts.map(p => p.name).join(' vs ')}</span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setComparedProducts([])}
                  className="px-2 py-1 rounded text-[10px] border border-slate-700 text-slate-400 hover:text-slate-200 cursor-pointer"
                >
                  Clear
                </button>
                <button
                  disabled={comparedProducts.length < 2}
                  onClick={handleTriggerComparison}
                  className={`px-3 py-1 rounded text-[10px] font-semibold text-white cursor-pointer transition-opacity ${
                    comparedProducts.length === 2 
                      ? 'bg-brand-600 hover:bg-brand-500' 
                      : 'bg-slate-800 text-slate-500 cursor-not-allowed'
                  }`}
                >
                  Run Comparison
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* 3. CHAT CONTENT SCROLL AREA */}
        <div className="flex-grow overflow-y-auto p-4 space-y-6">
          {isChatEmpty ? (
            /* EMPTY STATE HERO */
            <div className="flex flex-col items-center justify-center min-h-[70vh] text-center px-4">
              <motion.div
                initial={{ scale: 0.8, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                transition={{ duration: 0.5, type: 'spring' }}
                className="w-16 h-16 rounded-2xl bg-indigo-500/10 border border-brand-500/20 flex items-center justify-center shadow-lg shadow-indigo-950/20 mb-6"
              >
                <Sparkles className="w-8 h-8 text-brand-400" />
              </motion.div>
              
              <h1 className="text-2xl md:text-3xl font-extrabold text-white tracking-tight mb-2">
                Discover Your Perfect Product
              </h1>
              
              <p className="text-slate-400 text-xs md:text-sm max-w-md mb-8 leading-relaxed">
                Welcome! I am your AI Virtual Sales Associate. I can match items to your lifestyle, audit specifications, and run interactive matrices.
              </p>

              {/* Suggestions grid */}
              <SuggestedPrompts onSelect={handleSend} />
            </div>
          ) : (
            /* CHAT MESSAGES LOG */
            <div className="max-w-4xl mx-auto space-y-6 w-full pb-10">
              {activeConversation.messages.map((msg, index) => {
                const isBot = msg.role === 'assistant';
                return (
                  <motion.div
                    key={index}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.3 }}
                    className={`flex gap-4 ${isBot ? 'mr-auto max-w-[90%]' : 'ml-auto max-w-[85%] flex-row-reverse'}`}
                  >
                    {/* Message profile avatar */}
                    {isBot ? (
                      <div className="w-8 h-8 rounded-xl bg-indigo-950 border border-brand-500/20 flex items-center justify-center flex-shrink-0">
                        <Sparkles className="w-4 h-4 text-brand-400" />
                      </div>
                    ) : (
                      <div className="w-8 h-8 rounded-xl bg-slate-800 border border-slate-700 flex items-center justify-center flex-shrink-0 text-xs font-bold text-slate-300">
                        ME
                      </div>
                    )}

                    {/* Text Container bubble */}
                    <div className="flex flex-col gap-1.5 w-full">
                      <div className={`p-5 rounded-3xl ${
                        isBot 
                          ? 'glass-card bg-slate-800/40 border border-slate-700/50 shadow-[0_8px_30px_-4px_rgba(0,0,0,0.4)]' 
                          : 'bg-gradient-to-br from-indigo-600/20 to-violet-600/10 border border-indigo-500/30 text-slate-100 rounded-tr-sm shadow-[0_4px_20px_-4px_rgba(99,102,241,0.15)]'
                      }`}>
                        {/* Render textual content */}
                        <div className="text-sm font-light space-y-1 font-sans">
                          {formatMessageText(msg.content)}
                        </div>

                        {/* Search Context Badge */}
                        {isBot && msg.searchContext && (
                          <SearchContextBadge searchContext={msg.searchContext} />
                        )}

                        {/* Response Type Badge */}
                        {isBot && msg.responseType && (
                          <div className="flex gap-2 mb-2 mt-2">
                            <span className="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-300">
                              {msg.responseType}
                            </span>
                          </div>
                        )}

                        {/* Live discovery notification */}
                        {isBot && msg.system_notification && (
                          <div className="mt-3 flex items-center gap-2 p-2.5 px-4 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-semibold animate-pulse shadow-md shadow-emerald-950/20">
                            <AlertCircle className="w-4.5 h-4.5 text-emerald-400 shrink-0 animate-bounce" />
                            <span>{msg.system_notification}</span>
                          </div>
                        )}

                        {/* Interactive Product cards grid */}
                        {isBot && msg.products && msg.products.length > 0 && (
                          <div className="mt-5 pt-4 border-t border-slate-800/80">
                            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                              {msg.products.map((prod, idx) => (
                                <div key={`${prod.id || prod.product_url || prod.url || 'prod'}-${idx}`}>
                                  <ProductCard 
                                    product={prod}
                                    onCompareToggle={handleCompareToggle}
                                    isCompared={!!comparedProducts.find(p => (p.id || p.product_url) === (prod.id || prod.product_url))}
                                  />
                                </div>
                              ))}
                            </div>
                            {/* Show More / Pagination */}
                            {msg.paginationToken && (
                              <div className="flex justify-center mt-4">
                                <button
                                  onClick={() => loadMore(activeConversation?.messages.filter(m => m.role === 'user').pop()?.content || '', msg.paginationToken)}
                                  disabled={paginationLoading}
                                  className="flex items-center gap-2 px-6 py-2.5 rounded-xl bg-slate-800/60 border border-slate-700/50 text-sm text-slate-300 hover:text-white hover:bg-slate-800 hover:border-brand-500/30 cursor-pointer transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                                >
                                  {paginationLoading ? (
                                    <>
                                      <div className="w-4 h-4 border-2 border-slate-500 border-t-brand-400 rounded-full animate-spin"></div>
                                      <span>Loading...</span>
                                    </>
                                  ) : (
                                    <>
                                      <ChevronDown className="w-4 h-4" />
                                      <span>Show More</span>
                                    </>
                                  )}
                                </button>
                              </div>
                            )}
                          </div>
                        )}

                        {/* Bundle View */}
                        {isBot && msg.bundle && (
                          <div className="mt-4 pt-2 border-t border-slate-800/50">
                            <BundleView bundle={msg.bundle} />
                          </div>
                        )}

                        {/* Interactive Comparison views table */}
                        {isBot && msg.comparison && (
                          <div className="mt-4 pt-2 border-t border-slate-800/50">
                            <ComparisonPreviewCard 
                              comparison={msg.comparison} 
                              onOpen={() => setActiveComparison(msg.comparison)} 
                            />
                          </div>
                        )}

                        {/* Comparison Table from ShopMate */}
                        {isBot && msg.comparisonTable && (
                          <div className="mt-4 pt-2 border-t border-slate-800/50">
                            <ComparisonPreviewCard 
                              comparison={msg.comparisonTable} 
                              onOpen={() => setActiveComparison(msg.comparisonTable)} 
                            />
                          </div>
                        )}
                      </div>

                      {/* Pill Suggestion Quick Replies */}
                      {isBot && msg.followUps && msg.followUps.length > 0 && (
                        <div className="flex flex-wrap gap-2 mt-1">
                          {msg.followUps.map((q, qIdx) => (
                            <button
                              key={qIdx}
                              onClick={() => handleSend(q)}
                              className="text-[11px] font-medium bg-slate-850 hover:bg-slate-800/85 text-brand-300 hover:text-white border border-slate-800 hover:border-brand-500/30 px-3 py-1.5 rounded-full cursor-pointer transition-all"
                            >
                              {q}
                            </button>
                          ))}
                        </div>
                      )}
                      
                      {/* Timestamp */}
                      <span className={`text-[9px] text-slate-500 mt-0.5 ${isBot ? 'self-start' : 'self-end'}`}>
                        {msg.timestamp}
                      </span>
                    </div>
                  </motion.div>
                );
              })}

              {/* SKELETON FEEDBACK LOADER */}
              {loading && <SkeletonLoader />}

              {/* Ref point for scroll behavior */}
              <div ref={chatEndRef} />
            </div>
          )}
        </div>

        {/* 4. BOTTOM INPUT CONTEXT CONTROL */}
        <div className="p-4 border-t border-slate-800/60 bg-slate-900/30 backdrop-blur-md">
          <div className="max-w-4xl mx-auto">
            <div className="relative flex items-center rounded-2xl glass-input px-3 py-2">
              <textarea
                rows="1"
                disabled={loading}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask for recommendations, compare specs, or outline an lifestyle gear set..."
                className="flex-grow bg-transparent text-sm text-slate-200 placeholder-slate-500 focus:outline-none resize-none pl-2 pr-12 max-h-24 py-1"
              />
              <button
                disabled={loading || !input.trim()}
                onClick={() => handleSend()}
                className={`absolute right-3 p-2 rounded-xl flex items-center justify-center transition-all ${
                  input.trim() && !loading
                    ? 'bg-brand-600 hover:bg-brand-500 text-white cursor-pointer shadow-md'
                    : 'bg-slate-800 text-slate-600 cursor-not-allowed'
                }`}
              >
                <Send className="w-4 h-4" />
              </button>
            </div>
            <div className="flex items-center justify-between mt-2 px-2 text-[10px] text-slate-500">
              <span className="flex items-center gap-1">
                <Info className="w-3 h-3 text-brand-400" /> Enter to send, Shift + Enter for newline
              </span>
              <span>Local Recommender active</span>
            </div>
          </div>
        </div>

      </main>

      {/* 5. SLIDING CART DRAWER PANEL */}
      <AnimatePresence>
        {isCartOpen && (
          <>
            {/* Dark Backdrop */}
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 0.5 }}
              exit={{ opacity: 0 }}
              onClick={() => setIsCartOpen(false)}
              className="fixed inset-0 bg-black z-40"
            />

            {/* Cart Drawer */}
            <motion.div
              initial={{ x: '100%' }}
              animate={{ x: 0 }}
              exit={{ x: '100%' }}
              transition={{ type: 'tween', duration: 0.3 }}
              className="fixed top-0 right-0 h-full w-full sm:w-[400px] bg-slate-950 border-l border-slate-800 z-50 flex flex-col shadow-2xl"
            >
              {/* Cart Header */}
              <div className="p-4 border-b border-slate-800/80 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <ShoppingCart className="w-5 h-5 text-brand-400" />
                  <h3 className="font-bold text-white text-base">Your Shopping Cart</h3>
                </div>
                <button
                  onClick={() => setIsCartOpen(false)}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800/60 cursor-pointer"
                >
                  <X className="w-4.5 h-4.5" />
                </button>
              </div>

              {/* Cart items list */}
              <div className="flex-grow overflow-y-auto p-4 space-y-4">
                {checkoutSuccess ? (
                  <motion.div 
                    initial={{ scale: 0.95, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    className="flex flex-col items-center justify-center py-20 text-center"
                  >
                    <div className="w-12 h-12 rounded-full bg-emerald-500/20 border border-emerald-500/50 flex items-center justify-center mb-4">
                      <Check className="w-6 h-6 text-emerald-400" />
                    </div>
                    <h4 className="font-bold text-white text-lg mb-1">Order Processed!</h4>
                    <p className="text-xs text-slate-400 max-w-[250px]">Your simulated purchase is complete. Thank you for using the AI Sales Associate.</p>
                  </motion.div>
                ) : cart.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-24 text-slate-600 text-center">
                    <ShoppingBag className="w-12 h-12 mb-3 text-slate-800" />
                    <span className="text-sm font-semibold">Your cart is empty</span>
                    <span className="text-xs text-slate-700 mt-1">Ask the bot to suggest items to add!</span>
                  </div>
                ) : (
                  cart.map((item, idx) => (
                    <div key={`${item.id || item.product_url || item.url || 'cart'}-${idx}`} className="flex gap-3 p-3 rounded-xl bg-slate-900/60 border border-slate-800/50">
                      {item.image_url ? (
                        <img 
                          src={item.image_url} 
                          alt={item.name} 
                          className="w-16 h-16 object-cover rounded-lg bg-slate-950 border border-slate-800 flex-shrink-0"
                          onError={(e) => {
                            e.target.onerror = null;
                            e.target.src = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='100' height='100'><rect width='100' height='100' fill='%23020617'/><text x='50%25' y='50%25' dominant-baseline='middle' text-anchor='middle' font-family='sans-serif' font-size='10' fill='%23475569'>No Photo</text></svg>";
                          }}
                        />
                      ) : (
                        <div className="w-16 h-16 rounded-lg bg-slate-950 border border-slate-800 flex items-center justify-center text-[10px] text-slate-700 flex-shrink-0">
                          No Image
                        </div>
                      )}
                      <div className="flex-grow flex flex-col justify-between">
                        <div>
                          <h5 className="text-xs font-semibold text-white line-clamp-1">{item.name}</h5>
                          <span className="text-[10px] text-slate-500 block">{item.brand}</span>
                        </div>
                        <div className="flex justify-between items-center mt-1">
                          <span className="text-xs font-bold text-brand-300">₹{(item.price * item.quantity).toLocaleString('en-IN')}</span>
                          
                          {/* Quantity control */}
                          <div className="flex items-center border border-slate-800 rounded bg-slate-950 text-xs">
                            <button
                              onClick={() => updateCartQuantity(item.id, item.quantity - 1)}
                              className="px-1.5 py-0.5 hover:text-white text-slate-500 cursor-pointer"
                            >
                              -
                            </button>
                            <span className="px-2 py-0.5 text-slate-300 font-medium">{item.quantity}</span>
                            <button
                              onClick={() => updateCartQuantity(item.id, item.quantity + 1)}
                              className="px-1.5 py-0.5 hover:text-white text-slate-500 cursor-pointer"
                            >
                              +
                            </button>
                          </div>
                        </div>
                      </div>
                      
                      {/* Remove item */}
                      <button
                        onClick={() => removeFromCart(item.id)}
                        className="text-slate-500 hover:text-rose-400 p-1 self-start cursor-pointer"
                        title="Remove product"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  ))
                )}
              </div>

              {/* Cart Footer */}
              {!checkoutSuccess && cart.length > 0 && (
                <div className="p-4 border-t border-slate-800/80 bg-slate-950">
                  <div className="space-y-1.5 mb-4">
                    <div className="flex justify-between text-xs text-slate-400">
                      <span>Total Items</span>
                      <span>{cart.reduce((sum, item) => sum + item.quantity, 0)}</span>
                    </div>
                    <div className="flex justify-between text-sm font-bold text-white">
                      <span>Subtotal</span>
                      <span className="text-brand-300">₹{cartSubtotal.toLocaleString('en-IN')}</span>
                    </div>
                  </div>

                  <button
                    onClick={handleCheckout}
                    className="w-full py-3 bg-brand-600 hover:bg-brand-500 text-white font-bold text-xs rounded-xl shadow-lg shadow-indigo-950/40 border border-brand-400/20 cursor-pointer transition-all hover:scale-[1.01]"
                  >
                    Simulate Checkout Order
                  </button>
                </div>
              )}
            </motion.div>
          </>
        )}
      </AnimatePresence>

      {/* 6. SCREEN-SIZE COMPARISON POP UP PANEL */}
      <AnimatePresence>
        {activeComparison && (
          <>
            {/* Backdrop */}
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 0.7 }}
              exit={{ opacity: 0 }}
              onClick={() => setActiveComparison(null)}
              className="fixed inset-0 bg-black/80 z-50 backdrop-blur-sm"
            />

            {/* Screen-size Panel */}
            <motion.div
              initial={{ x: '100%' }}
              animate={{ x: 0 }}
              exit={{ x: '100%' }}
              transition={{ type: 'spring', damping: 26, stiffness: 170 }}
              className="fixed top-0 right-0 h-full w-full bg-slate-950 border-l border-slate-800 z-50 flex flex-col shadow-2xl overflow-hidden"
            >
              {/* Header */}
              <div className="p-5 border-b border-slate-800/80 bg-slate-900/50 backdrop-blur flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-indigo-500/10 border border-indigo-500/30 flex items-center justify-center">
                    <Activity className="w-5 h-5 text-brand-400" />
                  </div>
                  <div>
                    <h3 className="font-bold text-white text-base">Product Comparison Matrix</h3>
                    <p className="text-xs text-slate-400">Comparing technical specifications and AI evaluation</p>
                  </div>
                </div>
                <button
                  onClick={() => setActiveComparison(null)}
                  className="p-2 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800/60 border border-slate-800/80 cursor-pointer flex items-center gap-1.5 transition-all text-xs font-semibold"
                >
                  <X className="w-4.5 h-4.5" />
                  <span>Close Matrix</span>
                </button>
              </div>

              {/* Matrix Scroll Area */}
              <div className="flex-grow overflow-y-auto p-6 md:p-8 space-y-8">
                {/* Product Headers Block */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {/* Product 1 Info */}
                  {activeComparison.products?.[0] && (
                    <div className="relative p-5 rounded-2xl bg-gradient-to-br from-indigo-950/20 to-slate-900/40 border border-slate-800/80 flex flex-col sm:flex-row gap-4 items-start sm:items-center">
                      <div className="absolute top-3 left-3 bg-brand-500/10 text-brand-400 border border-brand-500/20 text-[9px] font-bold px-2.5 py-0.5 rounded-full uppercase">
                        Product A
                      </div>
                      {activeComparison.products[0].image_url || activeComparison.products[0].image ? (
                        <img 
                          src={activeComparison.products[0].image_url || activeComparison.products[0].image} 
                          alt={activeComparison.products[0].name} 
                          className="w-20 h-20 object-cover rounded-xl bg-slate-950 border border-slate-800/80 shrink-0"
                          onError={(e) => {
                            e.target.onerror = null;
                            e.target.src = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='100' height='100'><rect width='100' height='100' fill='%23020617'/><text x='50%25' y='50%25' dominant-baseline='middle' text-anchor='middle' font-family='sans-serif' font-size='10' fill='%23475569'>No Photo</text></svg>";
                          }}
                        />
                      ) : (
                        <div className="w-20 h-20 rounded-xl bg-slate-950 border border-slate-800 flex items-center justify-center text-xs text-slate-700 shrink-0">
                          No Photo
                        </div>
                      )}
                      <div className="flex-grow pt-4 sm:pt-0">
                        <span className="text-slate-400 text-[10px] uppercase font-bold tracking-wider">{activeComparison.products[0].brand || 'Brand'}</span>
                        <h4 className="text-white font-extrabold text-base line-clamp-2 mt-0.5">{activeComparison.products[0].name}</h4>
                        <div className="flex items-center gap-3 mt-2">
                          <span className="text-brand-300 font-extrabold text-lg">₹{activeComparison.products[0].price?.toLocaleString('en-IN')}</span>
                          {activeComparison.products[0].rating && (
                            <span className="text-amber-400 font-bold text-xs bg-amber-500/10 border border-amber-500/20 px-2 py-0.5 rounded-full flex items-center gap-1">
                              ★ {activeComparison.products[0].rating}
                            </span>
                          )}
                        </div>
                        <button
                          onClick={() => addToCart(activeComparison.products[0])}
                          className="mt-3 py-1.5 px-4 bg-brand-600 hover:bg-brand-500 text-white font-bold text-xs rounded-lg shadow-md cursor-pointer transition-colors flex items-center gap-1.5"
                        >
                          <ShoppingCart className="w-3.5 h-3.5" /> Add to Cart
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Product 2 Info */}
                  {activeComparison.products?.[1] && (
                    <div className="relative p-5 rounded-2xl bg-gradient-to-br from-indigo-950/20 to-slate-900/40 border border-slate-800/80 flex flex-col sm:flex-row gap-4 items-start sm:items-center">
                      <div className="absolute top-3 left-3 bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 text-[9px] font-bold px-2.5 py-0.5 rounded-full uppercase">
                        Product B
                      </div>
                      {activeComparison.products[1].image_url || activeComparison.products[1].image ? (
                        <img 
                          src={activeComparison.products[1].image_url || activeComparison.products[1].image} 
                          alt={activeComparison.products[1].name} 
                          className="w-20 h-20 object-cover rounded-xl bg-slate-950 border border-slate-800/80 shrink-0"
                          onError={(e) => {
                            e.target.onerror = null;
                            e.target.src = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='100' height='100'><rect width='100' height='100' fill='%23020617'/><text x='50%25' y='50%25' dominant-baseline='middle' text-anchor='middle' font-family='sans-serif' font-size='10' fill='%23475569'>No Photo</text></svg>";
                          }}
                        />
                      ) : (
                        <div className="w-20 h-20 rounded-xl bg-slate-950 border border-slate-800 flex items-center justify-center text-xs text-slate-700 shrink-0">
                          No Photo
                        </div>
                      )}
                      <div className="flex-grow pt-4 sm:pt-0">
                        <span className="text-slate-400 text-[10px] uppercase font-bold tracking-wider">{activeComparison.products[1].brand || 'Brand'}</span>
                        <h4 className="text-white font-extrabold text-base line-clamp-2 mt-0.5">{activeComparison.products[1].name}</h4>
                        <div className="flex items-center gap-3 mt-2">
                          <span className="text-brand-300 font-extrabold text-lg">₹{activeComparison.products[1].price?.toLocaleString('en-IN')}</span>
                          {activeComparison.products[1].rating && (
                            <span className="text-amber-400 font-bold text-xs bg-amber-500/10 border border-amber-500/20 px-2 py-0.5 rounded-full flex items-center gap-1">
                              ★ {activeComparison.products[1].rating}
                            </span>
                          )}
                        </div>
                        <button
                          onClick={() => addToCart(activeComparison.products[1])}
                          className="mt-3 py-1.5 px-4 bg-brand-600 hover:bg-brand-500 text-white font-bold text-xs rounded-lg shadow-md cursor-pointer transition-colors flex items-center gap-1.5"
                        >
                          <ShoppingCart className="w-3.5 h-3.5" /> Add to Cart
                        </button>
                      </div>
                    </div>
                  )}
                </div>

                {/* AI Overview Text Callout */}
                {activeComparison.overview && (
                  <div className="p-5 rounded-2xl bg-indigo-950/20 border border-indigo-500/20 shadow-inner">
                    <div className="flex items-center gap-2 mb-3">
                      <Sparkles className="w-5 h-5 text-indigo-400" />
                      <h4 className="font-bold text-white text-sm">AI Strategic Overview</h4>
                    </div>
                    <p className="text-slate-200 text-xs md:text-sm leading-relaxed font-light">
                      {activeComparison.overview}
                    </p>
                  </div>
                )}

                {/* Strengths Section */}
                {activeComparison.strengths && (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="p-4 rounded-xl bg-emerald-950/20 border border-emerald-500/20">
                      <h4 className="text-emerald-400 font-bold text-sm mb-2">
                        {activeComparison.products?.[0]?.name || 'Product A'} Strengths
                      </h4>
                      {(activeComparison.strengths.product_a || []).length > 0 ? (
                        <ul className="space-y-1">
                          {activeComparison.strengths.product_a.map((s, i) => (
                            <li key={i} className="text-slate-300 text-xs flex items-start gap-2">
                              <span className="text-emerald-400 mt-0.5">◆</span> {s}
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="text-slate-500 text-xs italic">No clear advantages</p>
                      )}
                    </div>
                    <div className="p-4 rounded-xl bg-indigo-950/20 border border-indigo-500/20">
                      <h4 className="text-indigo-400 font-bold text-sm mb-2">
                        {activeComparison.products?.[1]?.name || 'Product B'} Strengths
                      </h4>
                      {(activeComparison.strengths.product_b || []).length > 0 ? (
                        <ul className="space-y-1">
                          {activeComparison.strengths.product_b.map((s, i) => (
                            <li key={i} className="text-slate-300 text-xs flex items-start gap-2">
                              <span className="text-indigo-400 mt-0.5">◆</span> {s}
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="text-slate-500 text-xs italic">No clear advantages</p>
                      )}
                    </div>
                  </div>
                )}

                {/* Best Choice Banner */}
                {activeComparison.best_choice && (
                  <div className={`p-4 rounded-xl border text-center ${
                    activeComparison.best_choice === 'Product A'
                      ? 'bg-emerald-950/20 border-emerald-500/20'
                      : activeComparison.best_choice === 'Product B'
                        ? 'bg-indigo-950/20 border-indigo-500/20'
                        : 'bg-amber-950/20 border-amber-500/20'
                  }`}>
                    <span className={`font-bold text-sm ${
                      activeComparison.best_choice === 'Product A'
                        ? 'text-emerald-400'
                        : activeComparison.best_choice === 'Product B'
                          ? 'text-indigo-400'
                          : 'text-amber-400'
                    }`}>
                      {activeComparison.best_choice === 'Depends on your needs'
                        ? '⚖️ Recommendation: Depends on your needs — review the specs above'
                        : `Best Choice: ${activeComparison.best_choice}`}
                    </span>
                  </div>
                )}

                {/* Specs Table Matrix */}
                <div className="border border-slate-800 rounded-2xl overflow-hidden bg-slate-900/20">
                  <div className="bg-slate-900/50 p-4 border-b border-slate-800 flex items-center justify-between">
                    <span className="text-xs font-bold text-white uppercase tracking-wider">Specifications Comparison Matrix</span>
                    <span className="text-[10px] text-brand-400 px-2.5 py-0.5 rounded-full bg-brand-400/10 border border-brand-400/20 font-semibold">Side-by-Side</span>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs md:text-sm border-collapse">
                      <thead>
                        <tr className="border-b border-slate-800 bg-slate-950/40">
                          <th className="p-4 text-slate-400 font-semibold w-1/4">Specification</th>
                          <th className="p-4 border-l border-slate-800 text-white font-bold w-3/8 bg-indigo-950/5">
                            {activeComparison.products?.[0]?.brand} {activeComparison.products?.[0]?.name}
                          </th>
                          <th className="p-4 border-l border-slate-800 text-white font-bold w-3/8 bg-indigo-950/5">
                            {activeComparison.products?.[1]?.brand} {activeComparison.products?.[1]?.name}
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr className="border-b border-slate-800 hover:bg-slate-800/20">
                          <td className="p-4 text-slate-400 font-medium">Price</td>
                          <td className="p-4 border-l border-slate-800 text-brand-300 font-bold text-base">₹{activeComparison.products?.[0]?.price?.toLocaleString('en-IN')}</td>
                          <td className="p-4 border-l border-slate-800 text-brand-300 font-bold text-base">₹{activeComparison.products?.[1]?.price?.toLocaleString('en-IN')}</td>
                        </tr>
                        <tr className="border-b border-slate-800 hover:bg-slate-800/20">
                          <td className="p-4 text-slate-400 font-medium">Rating</td>
                          <td className="p-4 border-l border-slate-800 text-amber-400 font-semibold">{activeComparison.products?.[0]?.rating ? `★ ${activeComparison.products[0].rating}` : 'N/A'}</td>
                          <td className="p-4 border-l border-slate-800 text-amber-400 font-semibold">{activeComparison.products?.[1]?.rating ? `★ ${activeComparison.products[1].rating}` : 'N/A'}</td>
                        </tr>
                        {(activeComparison.specs || []).map((row, idx) => (
                          <tr key={idx} className="border-b border-slate-800 hover:bg-slate-800/20 last:border-0">
                            <td className="p-4 text-slate-400 font-medium">{row.feature}</td>
                            <td className="p-4 border-l border-slate-800 text-slate-300 font-light leading-relaxed">{row.val1 || 'N/A'}</td>
                            <td className="p-4 border-l border-slate-800 text-slate-300 font-light leading-relaxed">{row.val2 || 'N/A'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>

    </div>
  );
}

export default App;
