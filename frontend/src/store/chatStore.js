import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import axios from 'axios'

const API_BASE_URL = 'http://localhost:8000'

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
            products: data.products,
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
                  const updatedMsg = {
                    ...lastMsg,
                    products: [...lastMsg.products, ...newProducts],
                    paginationToken: newPaginationToken,
                    totalProducts: (lastMsg.totalProducts || 0) + newProducts.length
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
