import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import axios from 'axios'

const API_BASE_URL = 'http://localhost:8000'

const normalizeProductKey = (key) => {
  if (!key) return '';
  let str = String(key).trim();
  if (str.startsWith('http://') || str.startsWith('https://')) {
    try {
      const url = new URL(str);
      const pid = url.searchParams.get('pid');
      if (pid) {
        return `${url.origin}${url.pathname}?pid=${pid}`;
      }
      return `${url.origin}${url.pathname}`;
    } catch (e) {
      return str.split('?')[0];
    }
  }
  return str;
};

const deduplicateProducts = (products) => {
  if (!products) return [];
  const seen = new Set();
  return products.filter(p => {
    const key = p.id || p.product_url || p.url;
    if (!key) return true;
    const cleanKey = normalizeProductKey(key);
    if (seen.has(cleanKey)) {
      return false;
    }
    seen.add(cleanKey);
    return true;
  });
};

export const useChatStore = create(
  persist(
    (set, get) => ({
      conversations: [
        {
          id: 'welcome-chat',
          title: 'Shopping Assistance',
          messages: [
            {
              role: 'assistant',
              content: "Hello! I am your AI Shopping Assistant. I can help you discover products, compare specifications, and find the best deals. What are you looking for today?",
              timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
            }
          ],
          createdAt: new Date().toISOString(),
          paginationTokens: {}
        }
      ],
      activeConversationId: 'welcome-chat',
      cart: [],
      loading: false,
      paginationLoading: false,
      activeEventSource: null,

      setupStream: (chatId) => {
        const { activeEventSource } = get();
        if (activeEventSource) {
          activeEventSource.close();
        }

        if (!chatId || chatId === 'welcome-chat') {
          set({ activeEventSource: null });
          return;
        }

        const url = `${API_BASE_URL}/chat/stream/${chatId}`;
        const source = new EventSource(url);

        source.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            if (data.type === 'new_products') {
              const count = data.count;
              const newProducts = data.products || [];

              set((state) => {
                const conversations = state.conversations.map(c => {
                  if (c.id === chatId) {
                    const messages = [...c.messages];
                    const lastMsg = messages[messages.length - 1];
                    if (lastMsg && lastMsg.role === 'assistant') {
                      const currentProducts = lastMsg.products || [];
                      const combined = [...currentProducts, ...newProducts];
                      const uniqueProducts = deduplicateProducts(combined);
                      
                      const addedCount = uniqueProducts.length - currentProducts.length;
                      if (addedCount === 0) return c;

                      const updatedMsg = {
                        ...lastMsg,
                        products: uniqueProducts,
                        system_notification: `${addedCount} new product(s) found and appended below.`,
                        totalProducts: uniqueProducts.length
                      };
                      messages[messages.length - 1] = updatedMsg;
                    }
                    return { ...c, messages };
                  }
                  return c;
                });
                return { conversations };
              });
            }
          } catch (e) {
            console.error("Error parsing SSE event:", e);
          }
        };

        set({ activeEventSource: source });
      },

      setActiveConversation: (id) => set({ activeConversationId: id }),

      createNewChat: () => {
        const id = 'chat-' + Math.random().toString(36).substr(2, 9);
        const newChat = {
          id,
          title: 'New Conversation',
          messages: [
            {
              role: 'assistant',
              content: "Hello! I am your AI Shopping Assistant. Tell me what product or setup you are interested in, and I'll find you the best matching options!",
              timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
            }
          ],
          createdAt: new Date().toISOString(),
          paginationTokens: {}
        };
        set((state) => ({
          conversations: [newChat, ...state.conversations],
          activeConversationId: id
        }));
        return id;
      },

      deleteConversation: (id) => {
        set((state) => {
          const filtered = state.conversations.filter(c => c.id !== id);
          let newActive = state.activeConversationId;
          if (newActive === id) {
            newActive = filtered.length > 0 ? filtered[0].id : null;
          }
          return {
            conversations: filtered,
            activeConversationId: newActive
          };
        });
      },

      sendMessage: async (content) => {
        const { conversations, activeConversationId } = get();
        let chatId = activeConversationId;

        if (!chatId) {
          chatId = get().createNewChat();
        }

        const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        const userMsg = { role: 'user', content, timestamp };

        set((state) => ({
          conversations: state.conversations.map(c => {
            if (c.id === chatId) {
              const updatedMessages = [...c.messages, userMsg];
              const title = c.title === 'New Conversation' ? (content.length > 25 ? content.substring(0, 25) + '...' : content) : c.title;
              return { ...c, messages: updatedMessages, title, paginationTokens: { ...c.paginationTokens, [content]: null } };
            }
            return c;
          }),
          loading: true
        }));

        try {
          const activeChat = get().conversations.find(c => c.id === chatId);
          const response = await axios.post(`${API_BASE_URL}/chat`, {
            message: content,
            history: activeChat ? activeChat.messages : [],
            activeChatId: chatId
          });

          const data = response.data;
          const botMsg = {
            role: 'assistant',
            content: data.message || data.reply || '',
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
            products: deduplicateProducts(data.products),
            comparison: data.comparison,
            comparisonTable: data.comparison_table,
            bundle: data.bundle,
            searchContext: data.search_context,
            responseType: data.response_type,
            followUps: data.followUps || data.follow_up_questions || [],
            paginationToken: data.pagination_token,
            totalProducts: data.total_products
          };

          set((state) => ({
            conversations: state.conversations.map(c => {
              if (c.id === chatId) {
                const paginationTokens = { ...c.paginationTokens, [content]: data.pagination_token || null };
                return { ...c, messages: [...c.messages, botMsg], paginationTokens };
              }
              return c;
            }),
            loading: false
          }));

        } catch (error) {
          console.error("Failed to send message:", error);
          const errorMsg = {
            role: 'assistant',
            content: "Sorry, I encountered an error connecting to the server. Please make sure the backend server is running on port 8000.",
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
            followUps: ["Retry", "Laptops for Engineering", "Gym shoes and clothes"]
          };
          set((state) => ({
            conversations: state.conversations.map(c => {
              if (c.id === chatId) {
                return { ...c, messages: [...c.messages, errorMsg] };
              }
              return c;
            }),
            loading: false
          }));
        }
      },

      loadMore: async (query, currentPaginationToken) => {
        const { activeConversationId } = get();
        if (!activeConversationId || !currentPaginationToken) return;

        set({ paginationLoading: true });

        try {
          const response = await axios.post(`${API_BASE_URL}/chat?page_token=${currentPaginationToken}`, {
            message: query,
            history: [],
            activeChatId: activeConversationId
          });

          const data = response.data;
          const newProducts = data.products || [];
          const newPaginationToken = data.pagination_token || null;

          set((state) => ({
            conversations: state.conversations.map(c => {
              if (c.id === activeConversationId) {
                const lastMsg = c.messages[c.messages.length - 1];
                if (lastMsg && lastMsg.role === 'assistant' && lastMsg.products) {
                  const combined = [...lastMsg.products, ...newProducts];
                  const uniqueProducts = deduplicateProducts(combined);
                  const updatedMsg = {
                    ...lastMsg,
                    products: uniqueProducts,
                    paginationToken: newPaginationToken,
                    totalProducts: uniqueProducts.length
                  };
                  const messages = [...c.messages];
                  messages[messages.length - 1] = updatedMsg;
                  return { ...c, messages };
                }
              }
              return c;
            }),
            paginationLoading: false
          }));

        } catch (error) {
          console.error("Failed to load more products:", error);
          set({ paginationLoading: false });
        }
      },

      addToCart: (product) => {
        set((state) => {
          const itemExists = state.cart.find(item => item.id === product.id);
          if (itemExists) {
            return {
              cart: state.cart.map(item =>
                item.id === product.id ? { ...item, quantity: item.quantity + 1 } : item
              )
            };
          }
          return { cart: [...state.cart, { ...product, quantity: 1 }] };
        });
      },

      removeFromCart: (productId) => {
        set((state) => ({
          cart: state.cart.filter(item => item.id !== productId)
        }));
      },

      updateCartQuantity: (productId, quantity) => {
        set((state) => ({
          cart: state.cart.map(item =>
            item.id === productId ? { ...item, quantity: Math.max(1, quantity) } : item
          )
        }));
      },

      clearCart: () => set({ cart: [] })
    }),
    {
      name: 'ai-shopping-assistant-store',
      partialize: (state) => ({
        conversations: state.conversations,
        cart: state.cart,
        activeConversationId: state.activeConversationId
      }),
    }
  )
)
