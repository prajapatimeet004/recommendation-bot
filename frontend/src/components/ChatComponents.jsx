import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ShoppingCart, ShoppingBag, Star, Check, ArrowRight, Activity, Cpu, Sparkles, ChevronDown, ChevronUp, ExternalLink, Tag, Percent } from 'lucide-react';
import { useChatStore } from '../store/chatStore';

export const formatMessageText = (text) => {
  if (!text) return null;
  const lines = text.split('\n');
  const filteredLines = lines.filter(line => !line.startsWith('|'));

  return filteredLines.map((line, idx) => {
    let content = [];
    let parts = line.split('**');
    for (let i = 0; i < parts.length; i++) {
      if (i % 2 === 1) {
        content.push(<strong key={i} className="text-brand-300 font-semibold">{parts[i]}</strong>);
      } else {
        let subparts = parts[i].split('*');
        for (let j = 0; j < subparts.length; j++) {
          if (j % 2 === 1) {
            content.push(<em key={`${i}-${j}`} className="text-indigo-200 italic">{subparts[j]}</em>);
          } else {
            content.push(subparts[j]);
          }
        }
      }
    }

    if (line.trim().startsWith('* ') || line.trim().startsWith('- ')) {
      return (
        <li key={idx} className="ml-5 list-disc text-slate-300 mb-1.5 leading-relaxed">
          {content}
        </li>
      );
    }
    if (/^\d+\.\s/.test(line.trim())) {
      const cleanLine = line.trim().replace(/^\d+\.\s/, '');
      let listContent = [];
      let lParts = cleanLine.split('**');
      for (let i = 0; i < lParts.length; i++) {
        if (i % 2 === 1) {
          listContent.push(<strong key={i} className="text-brand-300 font-semibold">{lParts[i]}</strong>);
        } else {
          listContent.push(lParts[i]);
        }
      }
      return (
        <li key={idx} className="ml-5 list-decimal text-slate-300 mb-1.5 leading-relaxed">
          {listContent}
        </li>
      );
    }

    if (line.trim().startsWith('### ')) {
      return <h4 key={idx} className="text-md font-bold text-white mt-4 mb-1.5 border-b border-slate-700/50 pb-1">{line.replace('### ', '')}</h4>;
    }
    if (line.trim().startsWith('## ')) {
      return <h3 key={idx} className="text-lg font-bold text-white mt-5 mb-2 text-brand-300">{line.replace('## ', '')}</h3>;
    }
    if (line.trim().startsWith('# ')) {
      return <h2 key={idx} className="text-xl font-bold text-white mt-6 mb-2.5">{line.replace('# ', '')}</h2>;
    }

    return line.trim() === '' ? <div key={idx} className="h-3" /> : <p key={idx} className="text-slate-300 mb-2 leading-relaxed">{content}</p>;
  });
};

export const SuggestedPrompts = ({ onSelect }) => {
  const prompts = [
    {
      title: "Navratri Outfits",
      text: "I need clothes for Navratri",
      category: "Fashion",
      color: "from-amber-500/20 to-orange-500/10 hover:border-amber-500/40"
    },
    {
      title: "Camera Phone under ₹40k",
      text: "Suggest a phone under ₹40,000 with good camera",
      category: "Electronics",
      color: "from-emerald-500/20 to-teal-500/10 hover:border-emerald-500/40"
    },
    {
      title: "Coding Laptop",
      text: "Need a laptop for coding and programming",
      category: "Tech",
      color: "from-indigo-500/20 to-purple-500/10 hover:border-indigo-500/40"
    },
    {
      title: "Gym Gear Setup",
      text: "I'm joining a gym. What shoes and clothes should I buy?",
      category: "Fitness",
      color: "from-rose-500/20 to-pink-500/10 hover:border-rose-500/40"
    },
    {
      title: "Photography Phone",
      text: "Phone for photography",
      category: "Mobile",
      color: "from-blue-500/20 to-cyan-500/10 hover:border-blue-500/40"
    },
    {
      title: "Skincare Bundle",
      text: "Suggest a skincare bundle for summer",
      category: "Beauty",
      color: "from-violet-500/20 to-fuchsia-500/10 hover:border-violet-500/40"
    }
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 max-w-4xl mx-auto w-full px-4">
      {prompts.map((p, index) => (
        <motion.button
          key={index}
          initial={{ opacity: 0, y: 15 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: index * 0.05 }}
          onClick={() => onSelect(p.text)}
          className={`text-left p-4 rounded-xl border border-slate-700/50 glass-card bg-gradient-to-br ${p.color} flex flex-col justify-between h-32 group cursor-pointer`}
        >
          <div>
            <div className="flex justify-between items-center mb-2">
              <span className="font-semibold text-white text-md">{p.title}</span>
              <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700">{p.category}</span>
            </div>
            <p className="text-sm text-slate-400 group-hover:text-slate-200 transition-colors line-clamp-2">
              {p.text}
            </p>
          </div>
          <div className="flex items-center text-xs text-brand-400 font-medium self-end opacity-0 group-hover:opacity-100 transition-opacity">
            Ask Assistant <ArrowRight className="w-3 h-3 ml-1" />
          </div>
        </motion.button>
      ))}
    </div>
  );
};

export const ProductCard = ({ product, onCompareToggle, isCompared }) => {
  const addToCart = useChatStore(state => state.addToCart);
  const [showSpecs, setShowSpecs] = useState(false);
  const [added, setAdded] = useState(false);

  const handleAddToCart = () => {
    addToCart(product);
    setAdded(true);
    setTimeout(() => setAdded(false), 2000);
  };

  const hasDiscount = product.discount != null && product.discount > 0;
  const hasMrp = product.mrp != null && product.mrp > 0;
  const simScore = product.similarity_score;

  const sourceColors = {
    'flipkart.com': { bg: 'bg-blue-500/10', text: 'text-blue-400', border: 'border-blue-500/30' },
    'amazon.in': { bg: 'bg-amber-500/10', text: 'text-amber-400', border: 'border-amber-500/30' },
    'myntra.com': { bg: 'bg-rose-500/10', text: 'text-rose-400', border: 'border-rose-500/30' },
    'nykaa.com': { bg: 'bg-pink-500/10', text: 'text-pink-400', border: 'border-pink-500/30' },
    'croma.com': { bg: 'bg-emerald-500/10', text: 'text-emerald-400', border: 'border-emerald-500/30' },
    'ajio.com': { bg: 'bg-purple-500/10', text: 'text-purple-400', border: 'border-purple-500/30' },
  };
  const srcColor = sourceColors[product.source] || { bg: 'bg-slate-500/10', text: 'text-slate-400', border: 'border-slate-500/30' };

  return (
    <div className="flex flex-col rounded-xl overflow-hidden glass-card h-full border border-slate-700/50">
      <div className="relative h-44 overflow-hidden bg-slate-900 border-b border-slate-800">
        {product.image_url ? (
          <img
            src={product.image_url}
            alt={product.name}
            className="w-full h-full object-cover transition-transform duration-500 hover:scale-110"
            loading="lazy"
          />
        ) : (
          <div className="w-full h-full flex flex-col items-center justify-center bg-slate-950 text-slate-700 text-xs">
            <ShoppingBag className="w-8 h-8 mb-1.5 text-slate-800" />
            <span>No image available</span>
          </div>
        )}
        {/* Top-left: Similarity Score */}
        <div className="absolute top-2 left-2 flex gap-1">
          {simScore != null && (
            <div className="bg-indigo-950/80 backdrop-blur-md border border-indigo-500/30 px-2 py-1 rounded-lg text-[10px] font-semibold text-indigo-300">
              {simScore >= 90 ? 'Excellent' : simScore >= 80 ? 'Great' : 'Good'} Match
            </div>
          )}
        </div>
        {/* Top-right: Discount badge */}
        {hasDiscount && (
          <div className="absolute top-2 right-2 bg-rose-600/90 backdrop-blur-md border border-rose-400/50 px-2 py-1 rounded-lg text-[10px] font-bold text-white flex items-center gap-1">
            <Percent className="w-3 h-3" />
            {product.discount}% OFF
          </div>
        )}
      </div>

      <div className="p-4 flex flex-col flex-grow">
        {/* Brand + Source badge */}
        <div className="flex justify-between items-center mb-1.5">
          {product.brand && (
            <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">{product.brand}</span>
          )}
          <span className={`text-[9px] font-semibold px-1.5 py-0.5 rounded-full ${srcColor.bg} ${srcColor.text} ${srcColor.border} border`}>
            {product.source || 'Online Store'}
          </span>
        </div>

        {/* Product Name */}
        <h4 className="font-semibold text-white text-sm line-clamp-2 mb-1.5" title={product.name}>
          {product.name}
        </h4>

        {/* Rating */}
        {product.rating != null && product.rating > 0 && (
          <div className="flex items-center text-amber-400 text-xs mb-2">
            <Star className="w-3.5 h-3.5 fill-current mr-0.5" />
            <span className="font-medium">{product.rating}</span>
            <span className="text-slate-500 ml-1">/ 5</span>
          </div>
        )}

        {/* Price + MRP + Discount */}
        <div className="flex items-baseline gap-2 mb-2">
          {product.price != null && (
            <span className="text-xl font-bold text-white">
              ₹{Number(product.price).toLocaleString('en-IN')}
            </span>
          )}
          {hasMrp && product.price != null && product.mrp > product.price && (
            <span className="text-xs text-slate-500 line-through">
              ₹{Number(product.mrp).toLocaleString('en-IN')}
            </span>
          )}
          {hasDiscount && (
            <span className="text-[10px] font-semibold text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded">
              Save {product.discount}%
            </span>
          )}
        </div>

        {/* Description */}
        {product.description && (
          <p className="text-xs text-slate-400 mb-3 line-clamp-2 leading-relaxed">
            {product.description}
          </p>
        )}

        {/* Specs Toggle */}
        {product.specifications && Object.keys(product.specifications).length > 0 && (
          <>
            <button
              onClick={() => setShowSpecs(!showSpecs)}
              className="flex items-center justify-between w-full text-xs text-slate-400 bg-slate-800/40 hover:bg-slate-800/80 hover:text-slate-200 border border-slate-700/50 py-1.5 px-2.5 rounded-lg mb-3 transition-colors cursor-pointer"
            >
              <span className="font-medium">Specifications</span>
              {showSpecs ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            </button>

            <AnimatePresence>
              {showSpecs && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  className="overflow-hidden mb-3 border border-slate-800 rounded-lg bg-slate-900/60 text-[11px]"
                >
                  <div className="p-2 space-y-1">
                    {Object.entries(product.specifications).map(([key, val], idx) => (
                      <div key={`${key}-${idx}`} className="flex justify-between border-b border-slate-800/40 pb-1 last:border-0 last:pb-0">
                        <span className="text-slate-500 font-medium mr-2 capitalize">{key}</span>
                        <span className="text-slate-300 text-right font-light">{val}</span>
                      </div>
                    ))}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </>
        )}

        {/* Action Buttons */}
        <div className="flex gap-2 mt-auto">
          {onCompareToggle && (
            <button
              onClick={() => onCompareToggle(product)}
              className={`px-3 py-2 text-xs font-medium rounded-lg border flex items-center gap-1 cursor-pointer transition-colors ${
                isCompared
                  ? 'bg-indigo-500/20 border-indigo-500 text-brand-300'
                  : 'border-slate-700 text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
              }`}
            >
              {isCompared ? <Check className="w-3.5 h-3.5" /> : null}
              {isCompared ? 'Comparing' : 'Compare'}
            </button>
          )}

          {/* Buy Now button */}
          {product.product_url && (
            <a
              href={product.product_url}
              target="_blank"
              rel="noopener noreferrer"
              className="px-2.5 py-2 text-xs font-semibold rounded-lg border border-emerald-700/50 text-emerald-400 hover:bg-emerald-500/10 hover:text-emerald-300 flex items-center gap-1 cursor-pointer transition-colors"
            >
              <ExternalLink className="w-3.5 h-3.5" />
              <span>Buy on {product.source ? product.source.split('.')[0].charAt(0).toUpperCase() + product.source.split('.')[0].slice(1) : 'Store'}</span>
            </a>
          )}

          <button
            onClick={handleAddToCart}
            className={`flex-grow py-2 px-3 text-xs font-semibold rounded-lg flex items-center justify-center gap-1.5 cursor-pointer shadow-lg transition-all ${
              added
                ? 'bg-emerald-600 text-white shadow-emerald-950/20'
                : 'bg-brand-600 hover:bg-brand-500 text-white shadow-indigo-950/30'
            }`}
          >
            {added ? (
              <>
                <Check className="w-4 h-4" />
                <span>Added</span>
              </>
            ) : (
              <>
                <ShoppingCart className="w-4 h-4" />
                <span>Add to Cart</span>
              </>
            )}
          </button>
        </div>

        {/* Similarity score bar */}
        {simScore != null && (
          <div className="mt-2 pt-2 border-t border-slate-800/40">
            <div className="flex items-center justify-between text-[9px] text-slate-500 mb-1">
              <span>Match Score</span>
              <span className={simScore >= 80 ? 'text-emerald-400 font-semibold' : simScore >= 60 ? 'text-amber-400 font-semibold' : 'text-slate-400'}>
                {simScore}%
              </span>
            </div>
            <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${
                  simScore >= 80 ? 'bg-emerald-500' : simScore >= 60 ? 'bg-amber-500' : 'bg-slate-500'
                }`}
                style={{ width: `${Math.min(simScore, 100)}%` }}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export const ComparisonView = ({ comparison }) => {
  const addToCart = useChatStore(state => state.addToCart);

  if (!comparison || !comparison.products || comparison.products.length < 2) return null;
  const [prod1, prod2] = comparison.products;

  return (
    <div className="border border-slate-700/60 rounded-xl overflow-hidden glass-panel my-4 w-full shadow-lg">
      <div className="bg-slate-800/50 p-4 border-b border-slate-700 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity className="w-4.5 h-4.5 text-brand-400" />
          <h4 className="font-bold text-white text-sm">Comparison Matrix</h4>
        </div>
        <span className="text-[10px] text-slate-400 uppercase tracking-widest bg-slate-900 border border-slate-800 px-2 py-0.5 rounded-full">Specs Analysis</span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs border-collapse">
          <thead>
            <tr className="border-b border-slate-800 bg-slate-900/30">
              <th className="p-3 text-slate-400 font-semibold w-1/3">Feature</th>
              <th className="p-3 border-l border-slate-800/80 w-1/3">
                <div className="flex flex-col">
                  <span className="text-slate-400 text-[10px] font-medium">{prod1.brand}</span>
                  <span className="text-white font-bold text-sm line-clamp-1">{prod1.name}</span>
                  <span className="text-brand-300 font-bold mt-1 text-sm">₹{prod1.price?.toLocaleString('en-IN')}</span>
                </div>
              </th>
              <th className="p-3 border-l border-slate-800/80 w-1/3">
                <div className="flex flex-col">
                  <span className="text-slate-400 text-[10px] font-medium">{prod2.brand}</span>
                  <span className="text-white font-bold text-sm line-clamp-1">{prod2.name}</span>
                  <span className="text-brand-300 font-bold mt-1 text-sm">₹{prod2.price?.toLocaleString('en-IN')}</span>
                </div>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr className="border-b border-slate-800 hover:bg-slate-800/20">
              <td className="p-3 text-slate-400 font-medium">Rating</td>
              <td className="p-3 border-l border-slate-800/80 text-amber-400 font-semibold">{prod1.rating} ★</td>
              <td className="p-3 border-l border-slate-800/80 text-amber-400 font-semibold">{prod2.rating} ★</td>
            </tr>
            {(comparison.specs || []).map((row, idx) => (
              <tr key={idx} className="border-b border-slate-800 hover:bg-slate-800/20 last:border-0">
                <td className="p-3 text-slate-400 font-medium">{row.feature}</td>
                <td className="p-3 border-l border-slate-800/80 text-slate-300 font-light leading-relaxed">{row.val1}</td>
                <td className="p-3 border-l border-slate-800/80 text-slate-300 font-light leading-relaxed">{row.val2}</td>
              </tr>
            ))}
            <tr className="bg-slate-900/30 border-t border-slate-700/80">
              <td className="p-3"></td>
              <td className="p-3 border-l border-slate-800/80">
                <button
                  onClick={() => addToCart(prod1)}
                  className="w-full bg-brand-600 hover:bg-brand-500 text-white font-semibold py-1.5 px-3 rounded-lg text-[11px] flex items-center justify-center gap-1.5 cursor-pointer shadow transition-colors"
                >
                  <ShoppingCart className="w-3.5 h-3.5" /> Add {prod1.brand}
                </button>
              </td>
              <td className="p-3 border-l border-slate-800/80">
                <button
                  onClick={() => addToCart(prod2)}
                  className="w-full bg-brand-600 hover:bg-brand-500 text-white font-semibold py-1.5 px-3 rounded-lg text-[11px] flex items-center justify-center gap-1.5 cursor-pointer shadow transition-colors"
                >
                  <ShoppingCart className="w-3.5 h-3.5" /> Add {prod2.brand}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
};

export const BundleView = ({ bundle }) => {
  if (!bundle || !bundle.items) return null;

  return (
    <div className="border border-emerald-500/30 rounded-xl overflow-hidden glass-panel my-4 w-full shadow-lg">
      <div className="bg-emerald-900/20 p-4 border-b border-emerald-500/20 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ShoppingBag className="w-4.5 h-4.5 text-emerald-400" />
          <h4 className="font-bold text-white text-sm">{bundle.title || 'Recommended Bundle'}</h4>
        </div>
        {bundle.totalPrice && (
          <span className="text-sm font-bold text-emerald-300 bg-emerald-950/40 px-3 py-1 rounded-full border border-emerald-500/20">
            Bundle: ₹{bundle.totalPrice.toLocaleString('en-IN')}
          </span>
        )}
      </div>
      <div className="p-4 space-y-3">
        {bundle.items.map((item, idx) => (
          <div key={idx} className="flex gap-3 p-3 rounded-xl bg-slate-900/60 border border-slate-800/50">
            {item.image_url && (
              <img src={item.image_url} alt={item.name} className="w-14 h-14 object-cover rounded-lg bg-slate-950 border border-slate-800 flex-shrink-0" />
            )}
            <div className="flex-grow">
              <div className="flex justify-between items-start">
                <div>
                  <h5 className="text-xs font-semibold text-white">{item.name}</h5>
                  <span className="text-[10px] text-slate-500">{item.brand} — {item.category}</span>
                </div>
                <span className="text-xs font-bold text-emerald-300">₹{item.price?.toLocaleString('en-IN')}</span>
              </div>
              {item.why_recommended && (
                <p className="text-[10px] text-slate-400 mt-1 italic">{item.why_recommended}</p>
              )}
            </div>
          </div>
        ))}
        {bundle.reason && (
          <p className="text-xs text-slate-400 mt-2 pt-2 border-t border-slate-800/50">{bundle.reason}</p>
        )}
      </div>
    </div>
  );
};

export const SearchContextBadge = ({ searchContext }) => {
  if (!searchContext) return null;

  return (
    <div className="flex flex-wrap items-center gap-2 mb-3 text-[10px]">
      <span className={`px-2 py-0.5 rounded-full font-medium ${
        searchContext.data_source === 'cached'
          ? 'bg-amber-500/10 border border-amber-500/20 text-amber-300'
          : 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-300'
      }`}>
        {searchContext.data_source === 'cached' ? '⚡ Cached' : '🟢 Live'}
      </span>
      {searchContext.keywords_used && (
        <span className="text-slate-500">
          Keywords: <span className="text-slate-400 font-medium">{searchContext.keywords_used}</span>
        </span>
      )}
    </div>
  );
};

export const SkeletonLoader = () => {
  return (
    <div className="flex gap-4 p-4 rounded-2xl glass-card bg-slate-800/25 max-w-[85%] mr-auto items-start animate-pulse">
      <div className="w-8 h-8 rounded-xl bg-indigo-950 border border-brand-500/20 flex items-center justify-center flex-shrink-0">
        <Sparkles className="w-4 h-4 text-brand-400" />
      </div>

      <div className="flex-grow space-y-3.5">
        <div className="h-4 bg-slate-700/60 rounded w-11/12"></div>
        <div className="h-4 bg-slate-700/60 rounded w-10/12"></div>
        <div className="h-4 bg-slate-700/60 rounded w-8/12"></div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-4">
          <div className="border border-slate-800 rounded-xl overflow-hidden bg-slate-900/30 h-44 flex flex-col justify-end p-3 gap-2">
            <div className="h-4 bg-slate-800/80 rounded w-3/4"></div>
            <div className="h-3 bg-slate-800/80 rounded w-1/2"></div>
            <div className="h-6 bg-slate-800/80 rounded w-full mt-2"></div>
          </div>
          <div className="border border-slate-800 rounded-xl overflow-hidden bg-slate-900/30 h-44 flex flex-col justify-end p-3 gap-2">
            <div className="h-4 bg-slate-800/80 rounded w-3/4"></div>
            <div className="h-3 bg-slate-800/80 rounded w-1/2"></div>
            <div className="h-6 bg-slate-800/80 rounded w-full mt-2"></div>
          </div>
        </div>
      </div>
    </div>
  );
};
