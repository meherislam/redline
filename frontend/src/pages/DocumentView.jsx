import { useEffect, useState, useCallback, useRef } from 'react';
import {
  getDocument,
  getChunks,
  applyChanges,
  getChangeHistory,
  acceptChange,
  rejectChange,
  getOccurrences,
  suggestReplacement,
} from '../api/client';

function timeAgo(dateStr) {
  const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
  if (seconds < 60) return 'Just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(dateStr).toLocaleDateString();
}

export default function DocumentView({ documentId, initialHighlightChunkId, initialPage, onBack }) {
  const [doc, setDoc] = useState(null);
  const [chunks, setChunks] = useState([]);
  const [page, setPage] = useState(initialPage || 1);
  const [totalChunks, setTotalChunks] = useState(0);
  const [error, setError] = useState(null);
  const [successMsg, setSuccessMsg] = useState(null);

  // Popover redline
  const [popover, setPopover] = useState(null);
  const [popoverMode, setPopoverMode] = useState(null); // null | 'replace'
  const [replaceText, setReplaceText] = useState('');
  const [applying, setApplying] = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  const [suggestInstruction, setSuggestInstruction] = useState('');

  // Find + Replace All
  const [searchQuery, setSearchQuery] = useState('');
  const [occurrences, setOccurrences] = useState(null);
  const [highlightChunkId, setHighlightChunkId] = useState(initialHighlightChunkId || null);
  const [replaceAllText, setReplaceAllText] = useState('');
  const [applyingReplaceAll, setApplyingReplaceAll] = useState(false);

  // Changes panel (combined redlines + history)
  const [showChanges, setShowChanges] = useState(false);
  const [allChanges, setAllChanges] = useState([]);

  // Group highlighting
  const [highlightedGroupId, setHighlightedGroupId] = useState(null);

  const PAGE_SIZE = 50;
  const contentRef = useRef(null);
  const paperRef = useRef(null);
  const replaceInputRef = useRef(null);
  const didScrollToInitial = useRef(false);

  const loadDoc = useCallback(async () => {
    try {
      const data = await getDocument(documentId);
      setDoc(data);
    } catch (e) {
      setError(e.message);
    }
  }, [documentId]);

  const loadChunks = useCallback(async (p) => {
    try {
      const data = await getChunks(documentId, p, PAGE_SIZE);
      setChunks(data.chunks);
      setTotalChunks(data.total_chunks);
    } catch (e) {
      setError(e.message);
    }
  }, [documentId]);

  const loadChanges = useCallback(async () => {
    try {
      const data = await getChangeHistory(documentId);
      setAllChanges(data.changes);
    } catch (e) {
      setError(e.message);
    }
  }, [documentId]);

  useEffect(() => {
    loadDoc();
    loadChunks(page);
    loadChanges();
  }, [loadDoc, loadChunks, loadChanges, page]);

  // Scroll to highlighted chunk from global search
  useEffect(() => {
    if (initialHighlightChunkId && chunks.length > 0 && !didScrollToInitial.current) {
      didScrollToInitial.current = true;
      setTimeout(() => {
        const el = document.getElementById(`chunk-${initialHighlightChunkId}`);
        if (el) {
          el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
        setTimeout(() => setHighlightChunkId(null), 4000);
      }, 100);
    }
  }, [initialHighlightChunkId, chunks]);

  // Scroll to highlighted chunk after page change loads new chunks
  useEffect(() => {
    if (highlightChunkId && !initialHighlightChunkId && chunks.length > 0) {
      setTimeout(() => {
        const el = document.getElementById(`chunk-${highlightChunkId}`);
        if (el) {
          el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
        setTimeout(() => setHighlightChunkId(null), 4000);
      }, 100);
    }
  }, [chunks, highlightChunkId]);

  useEffect(() => {
    if (successMsg) {
      const t = setTimeout(() => setSuccessMsg(null), 3000);
      return () => clearTimeout(t);
    }
  }, [successMsg]);

  useEffect(() => {
    if (popoverMode === 'replace' && replaceInputRef.current) {
      const el = replaceInputRef.current;
      el.focus();
      el.style.height = 'auto';
      el.style.height = el.scrollHeight + 'px';
    }
  }, [popoverMode, replaceText]);

  useEffect(() => {
    function handleClickOutside(e) {
      if (popover && !e.target.closest('.redline-popover') && !e.target.closest('.doc-paragraph')) {
        setPopover(null);
        setPopoverMode(null);
        setReplaceText('');
        setSuggestInstruction('');
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [popover]);

  function getInvolvedChunks(startChunkId, endChunkId, range) {
    const startIdx = chunks.findIndex((c) => c.id === startChunkId);
    const endIdx = chunks.findIndex((c) => c.id === endChunkId);
    if (startIdx === -1 || endIdx === -1) return null;

    const [fromIdx, toIdx] = startIdx <= endIdx ? [startIdx, endIdx] : [endIdx, startIdx];
    const result = [];

    for (let i = fromIdx; i <= toIdx; i++) {
      const chunk = chunks[i];
      if (i === fromIdx && i === toIdx) {
        // Shouldn't happen (same chunk), but handle gracefully
        const selectedText = range.toString().trim();
        if (selectedText) result.push({ chunkId: chunk.id, selectedText });
      } else if (i === fromIdx) {
        // First chunk: find selected portion as suffix of chunk content
        const fullText = range.toString();
        // Get text from the start of the range to the end of the first chunk
        const chunkEl = document.getElementById(`chunk-${chunk.id}`);
        if (chunkEl) {
          const chunkRange = document.createRange();
          chunkRange.setStart(range.startContainer, range.startOffset);
          chunkRange.setEndAfter(chunkEl.lastChild || chunkEl);
          const selectedText = chunkRange.toString().trim();
          if (selectedText) result.push({ chunkId: chunk.id, selectedText });
        }
      } else if (i === toIdx) {
        // Last chunk: find selected portion as prefix of chunk content
        const chunkEl = document.getElementById(`chunk-${chunk.id}`);
        if (chunkEl) {
          const chunkRange = document.createRange();
          chunkRange.setStartBefore(chunkEl.firstChild || chunkEl);
          chunkRange.setEnd(range.endContainer, range.endOffset);
          const selectedText = chunkRange.toString().trim();
          if (selectedText) result.push({ chunkId: chunk.id, selectedText });
        }
      } else {
        // Middle chunk: entire content
        result.push({ chunkId: chunk.id, selectedText: chunk.content });
      }
    }

    return result.length > 0 ? result : null;
  }

  function handleTextSelect(chunkId, e) {
    const selection = window.getSelection();
    const text = selection?.toString()?.trim();
    if (!text || text.length === 0) return;

    const range = selection.getRangeAt(0);

    // Detect which chunk containers the selection starts and ends in
    const findChunkEl = (node) => {
      const el = node.nodeType === Node.TEXT_NODE ? node.parentElement : node;
      return el?.closest?.('[id^="chunk-"]');
    };
    const startChunkEl = findChunkEl(range.startContainer);
    const endChunkEl = findChunkEl(range.endContainer);
    if (!startChunkEl || !endChunkEl) return;

    const startChunkId = startChunkEl.id.replace('chunk-', '');
    const endChunkId = endChunkEl.id.replace('chunk-', '');

    const rect = range.getBoundingClientRect();
    const contentEl = contentRef.current;
    if (!contentEl) return;
    const contentRect = contentEl.getBoundingClientRect();

    const popoverBase = {
      text,
      top: rect.bottom - contentRect.top + contentEl.scrollTop + 8,
      left: rect.left - contentRect.left + rect.width / 2,
    };

    if (startChunkId === endChunkId) {
      // Single-chunk selection — calculate which occurrence was selected
      const chunk = chunks.find((c) => c.id === startChunkId);
      let occurrence = 1;
      if (chunk) {
        // Get character offset of selection start within the chunk's text
        const chunkEl = document.getElementById(`chunk-${startChunkId}`);
        if (chunkEl) {
          const preRange = document.createRange();
          preRange.setStartBefore(chunkEl.firstChild || chunkEl);
          preRange.setEnd(range.startContainer, range.startOffset);
          const offsetInChunk = preRange.toString().length;
          // Count how many times the selected text appears before this offset
          let searchFrom = 0;
          let count = 0;
          while (searchFrom <= offsetInChunk) {
            const idx = chunk.content.indexOf(text, searchFrom);
            if (idx === -1 || idx > offsetInChunk) break;
            count++;
            if (idx === offsetInChunk) break;
            searchFrom = idx + text.length;
          }
          occurrence = Math.max(1, count);
        }
      }
      setPopover({ ...popoverBase, chunkId: startChunkId, occurrence });
    } else {
      // Cross-chunk selection
      const involvedChunks = getInvolvedChunks(startChunkId, endChunkId, range);
      if (!involvedChunks || involvedChunks.length === 0) return;
      setPopover({
        ...popoverBase,
        chunkId: startChunkId,
        crossChunk: involvedChunks,
      });
    }
    setPopoverMode(null);
    setReplaceText('');
  }

  async function refreshAfterChange() {
    await loadDoc();
    await loadChunks(page);
    await loadChanges();
  }

  async function handleApplyChange(e) {
    e.preventDefault();
    if (!popover || !replaceText || !doc) return;
    setApplying(true);
    setError(null);
    try {
      const groupId = crypto.randomUUID();
      let changes;
      if (popover.crossChunk) {
        // Cross-chunk: replacement goes to first chunk, rest are deletions
        changes = popover.crossChunk.map(({ chunkId, selectedText }, i) => ({
          chunk_id: chunkId,
          old_text: selectedText,
          new_text: i === 0 ? replaceText : '',
          occurrence: 1,
          group_id: groupId,
        }));
      } else {
        changes = [
          { chunk_id: popover.chunkId, old_text: popover.text, new_text: replaceText, occurrence: popover.occurrence || 1, group_id: groupId },
        ];
      }
      await applyChanges(documentId, doc.version, changes);
      setPopover(null);
      setPopoverMode(null);
      setReplaceText('');
      window.getSelection()?.removeAllRanges();
      setSuccessMsg('Change applied');
      await refreshAfterChange();
    } catch (e) {
      setError(e.message);
    } finally {
      setApplying(false);
    }
  }

  async function handleDeleteChange() {
    if (!popover || !doc) return;
    setApplying(true);
    setError(null);
    try {
      const groupId = crypto.randomUUID();
      let changes;
      if (popover.crossChunk) {
        changes = popover.crossChunk.map(({ chunkId, selectedText }) => ({
          chunk_id: chunkId,
          old_text: selectedText,
          new_text: '',
          occurrence: 1,
          group_id: groupId,
        }));
      } else {
        changes = [
          { chunk_id: popover.chunkId, old_text: popover.text, new_text: '', occurrence: popover.occurrence || 1, group_id: groupId },
        ];
      }
      await applyChanges(documentId, doc.version, changes);
      setPopover(null);
      setPopoverMode(null);
      setReplaceText('');
      window.getSelection()?.removeAllRanges();
      setSuccessMsg('Deletion applied');
      await refreshAfterChange();
    } catch (e) {
      setError(e.message);
    } finally {
      setApplying(false);
    }
  }

  async function handleSuggest(e) {
    if (e) e.preventDefault();
    if (!popover) return;
    setSuggesting(true);
    setError(null);
    try {
      const instruction = suggestInstruction.trim() || undefined;
      const data = await suggestReplacement(documentId, popover.chunkId, popover.text, instruction);
      setReplaceText(data.suggestion);
      setSuggestInstruction('');
      setPopoverMode('replace');
    } catch (e) {
      setError(e.message);
    } finally {
      setSuggesting(false);
    }
  }

  async function handleSearch(e) {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    setError(null);
    try {
      const data = await getOccurrences(documentId, searchQuery.trim());
      setOccurrences(data);
    } catch (e) {
      setError(e.message);
    }
  }

  function handleClearSearch() {
    setSearchQuery('');
    setOccurrences(null);
    setReplaceAllText('');
  }

  const occurrenceTotal = occurrences ? occurrences.total_chunks : 0;

  async function handleReplaceAll() {
    if (!searchQuery.trim() || !replaceAllText || !doc || !occurrences || occurrences.matches.length === 0) return;
    setApplyingReplaceAll(true);
    setError(null);
    try {
      const term = searchQuery.trim();
      const groupId = crypto.randomUUID();
      const changes = [];
      for (const match of occurrences.matches) {
        changes.push({
          chunk_id: match.chunk_id,
          old_text: term,
          new_text: replaceAllText,
          occurrence: 1,
          group_id: groupId,
        });
      }
      await applyChanges(documentId, doc.version, changes);
      setSuccessMsg(`Replacements added as pending changes`);
      setReplaceAllText('');
      setOccurrences(null);
      setShowChanges(true);
      await refreshAfterChange();
    } catch (e) {
      setError(e.message);
    } finally {
      setApplyingReplaceAll(false);
    }
  }

  function handleSearchResultClick(chunkId, chunkPosition) {
    // Calculate which page this chunk lives on and switch if needed
    if (chunkPosition) {
      const targetPage = Math.ceil(chunkPosition / PAGE_SIZE);
      if (targetPage !== page) {
        setPage(targetPage);
        setHighlightChunkId(chunkId);
        // Scroll will happen after chunks reload via the useEffect
        return;
      }
    }
    setHighlightChunkId(chunkId);
    const el = document.getElementById(`chunk-${chunkId}`);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    setTimeout(() => setHighlightChunkId(null), 4000);
  }

  // Accept/Reject handlers
  async function handleAccept(changeId) {
    setError(null);
    try {
      const result = await acceptChange(documentId, changeId);
      setSuccessMsg('Change accepted');
      if (result.chunks) setChunks(result.chunks);
      const groupIds = new Set(result.group_change_ids || [changeId]);
      setAllChanges((prev) => prev.map((c) => groupIds.has(c.id) ? { ...c, status: 'accepted' } : c));
    } catch (e) {
      setError(e.message);
    }
  }

  async function handleReject(changeId) {
    setError(null);
    try {
      const result = await rejectChange(documentId, changeId);
      setSuccessMsg('Change rejected');
      if (result.chunks) setChunks(result.chunks);
      await loadDoc();
      const groupIds = new Set(result.group_change_ids || [changeId]);
      setAllChanges((prev) => prev.map((c) => groupIds.has(c.id) ? { ...c, status: 'rejected' } : c));
    } catch (e) {
      setError(e.message);
    }
  }

  // Derive pending changes from allChanges
  const pendingChanges = allChanges.filter((c) => c.status === 'pending');
  const pendingCount = pendingChanges.length;
  const resolvedChanges = allChanges.filter((c) => c.status !== 'pending');

  // Check if a change_group_id has more than one member (is a true cross-chunk group)
  function isMultiMemberGroup(groupId) {
    if (!groupId) return false;
    return pendingChanges.filter((c) => c.change_group_id === groupId).length > 1;
  }

  // Render chunk content with redline markup for pending changes
  function renderChunkWithRedlines(chunk) {
    const chunkChanges = pendingChanges.filter((c) => c.chunk_id === chunk.id);
    if (chunkChanges.length === 0) return chunk.content;

    let content = chunk.content;
    const parts = [];
    let key = 0;

    // Position each change in the current content
    const positioned = [];
    for (const change of chunkChanges) {
      if (change.new_text === '') {
        // Deletion: old_text was removed, use stored offset as insertion point
        if (change.old_text_offset != null) {
          positioned.push({ ...change, idx: change.old_text_offset, isDeletion: true });
        }
      } else {
        const idx = content.indexOf(change.new_text);
        if (idx !== -1) {
          positioned.push({ ...change, idx, isDeletion: false });
        }
      }
    }
    positioned.sort((a, b) => a.idx - b.idx);

    let lastIndex = 0;
    for (const change of positioned) {
      // Add text before this change
      if (change.idx > lastIndex) {
        parts.push(content.slice(lastIndex, change.idx));
      }

      const isGrouped = isMultiMemberGroup(change.change_group_id);
      const isHighlighted = isGrouped && highlightedGroupId === change.change_group_id;
      const classes = [
        'redline-inline',
        isGrouped ? 'redline-grouped' : '',
        isHighlighted ? 'redline-group-highlight' : '',
      ].filter(Boolean).join(' ');

      // Add the redline markup
      parts.push(
        <span
          key={key++}
          className={classes}
          data-group-id={isGrouped ? change.change_group_id : undefined}
          onMouseEnter={isGrouped ? () => setHighlightedGroupId(change.change_group_id) : undefined}
          onMouseLeave={isGrouped ? () => setHighlightedGroupId(null) : undefined}
        >
          <del className="redline-del">{change.old_text}</del>
          {!change.isDeletion && <ins className="redline-ins">{change.new_text}</ins>}
          <span className="redline-actions">
            <button
              className="redline-accept"
              title={isGrouped ? 'Accept all changes in group' : 'Accept change'}
              onClick={(e) => { e.stopPropagation(); handleAccept(change.id); }}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            </button>
            <button
              className="redline-reject"
              title={isGrouped ? 'Reject all changes in group' : 'Reject change'}
              onClick={(e) => { e.stopPropagation(); handleReject(change.id); }}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </span>
        </span>
      );

      // For deletions, no content was consumed; for replacements, skip past new_text
      lastIndex = change.isDeletion ? change.idx : change.idx + change.new_text.length;
    }

    // Add remaining text
    if (lastIndex < content.length) {
      parts.push(content.slice(lastIndex));
    }

    return parts.length > 0 ? parts : content;
  }

  // Highlight search term inline in chunk content (case-sensitive to match replace-all behavior)
  function highlightChunkContent(content) {
    if (!occurrences || !searchQuery.trim()) return content;
    const term = searchQuery.trim();
    const parts = [];
    let lastIndex = 0;
    let idx = 0;
    let key = 0;
    while (true) {
      idx = content.indexOf(term, lastIndex);
      if (idx === -1) break;
      if (idx > lastIndex) {
        parts.push(content.slice(lastIndex, idx));
      }
      parts.push(<mark key={key++} className="find-highlight">{content.slice(idx, idx + term.length)}</mark>);
      lastIndex = idx + term.length;
    }
    if (lastIndex < content.length) {
      parts.push(content.slice(lastIndex));
    }
    return parts.length > 0 ? parts : content;
  }

  // Choose which rendering to use for a chunk
  function renderChunk(chunk) {
    if (showChanges && pendingChanges.length > 0) {
      return renderChunkWithRedlines(chunk);
    }
    return highlightChunkContent(chunk.content);
  }

  const totalPages = Math.ceil(totalChunks / PAGE_SIZE);

  return (
    <div className="doc-view">
      {/* Toolbar */}
      <div className="doc-toolbar">
        <div className="doc-toolbar-left">
          <button className="toolbar-back" onClick={onBack} title="Back to documents">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="19" y1="12" x2="5" y2="12" />
              <polyline points="12 19 5 12 12 5" />
            </svg>
          </button>
          {doc && <h1 className="doc-title">{doc.title}</h1>}
        </div>
        <div className="doc-toolbar-right">
          <form onSubmit={handleSearch} className="toolbar-search">
            <svg className="search-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input
              type="text"
              placeholder="Find in document..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            {searchQuery && (
              <button type="button" className="search-clear" onClick={handleClearSearch}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            )}
          </form>
          <button
            className={`toolbar-btn ${showChanges ? 'active' : ''}`}
            onClick={() => setShowChanges((v) => !v)}
            title="Changes"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
            </svg>
            <span>Changes</span>
            {pendingCount > 0 && (
              <span className="toolbar-badge">{pendingCount}</span>
            )}
          </button>
        </div>
      </div>

      {/* Toasts */}
      {error && (
        <div className="toast toast-error">
          <span>{error}</span>
          <button onClick={() => setError(null)}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
      )}
      {successMsg && (
        <div className="toast toast-success"><span>{successMsg}</span></div>
      )}

      <div className="doc-body">
        {/* Document */}
        <div className="doc-content" ref={contentRef}>
          <div className="doc-paper" ref={paperRef}>
            {doc && <div className="paper-title">{doc.title}</div>}
            {chunks.map((chunk) => (
              <p
                key={chunk.id}
                id={`chunk-${chunk.id}`}
                className={`doc-paragraph ${highlightChunkId === chunk.id ? 'flash' : ''}`}
                onMouseUp={(e) => handleTextSelect(chunk.id, e)}
              >
                {renderChunk(chunk)}
              </p>
            ))}

            {totalPages > 1 && (
              <div className="doc-pagination">
                <button disabled={page <= 1} onClick={() => { setPage(page - 1); contentRef.current?.scrollTo(0, 0); }}>Previous</button>
                <span className="pagination-info">Page {page} of {totalPages}</span>
                <button disabled={page >= totalPages} onClick={() => { setPage(page + 1); contentRef.current?.scrollTo(0, 0); }}>Next</button>
              </div>
            )}
          </div>

          {/* Floating redline popover */}
          {popover && (
            <div
              className="redline-popover"
              style={{ top: popover.top, left: popover.left }}
            >
              <div className="popover-selected">
                <span className="popover-old">{popover.text}</span>
              </div>
              {popoverMode === null ? (
                <div className="popover-actions">
                  <button className="popover-action-btn popover-replace-btn" onClick={() => setPopoverMode('replace')} disabled={applying || suggesting}>
                    Replace
                  </button>
                  <button className="popover-action-btn popover-delete-btn" onClick={handleDeleteChange} disabled={applying || suggesting}>
                    {applying ? '...' : 'Delete'}
                  </button>
                  <button className="popover-action-btn popover-suggest-btn" onClick={() => setPopoverMode('suggest')} disabled={applying || suggesting || !!popover?.crossChunk}>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M12 2a7 7 0 0 1 7 7c0 2.38-1.19 4.47-3 5.74V17a2 2 0 0 1-2 2h-4a2 2 0 0 1-2-2v-2.26C6.19 13.47 5 11.38 5 9a7 7 0 0 1 7-7z" />
                      <line x1="9" y1="21" x2="15" y2="21" />
                    </svg>
                    {' '}Suggest
                  </button>
                  <button type="button" className="popover-cancel" onClick={() => { setPopover(null); setPopoverMode(null); setReplaceText(''); setSuggestInstruction(''); window.getSelection()?.removeAllRanges(); }}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                  </button>
                </div>
              ) : popoverMode === 'suggest' ? (
                <form onSubmit={handleSuggest} className="popover-form">
                  <input
                    type="text"
                    placeholder="e.g. Make more formal, Simplify, Fix grammar..."
                    value={suggestInstruction}
                    onChange={(e) => setSuggestInstruction(e.target.value)}
                    autoFocus
                  />
                  <div className="popover-form-actions">
                    <button type="submit" disabled={suggesting} className="popover-suggest-submit">
                      {suggesting ? <span className="suggest-spinner" /> : 'Suggest'}
                    </button>
                    <button type="button" className="popover-cancel" onClick={() => { setPopoverMode(null); setSuggestInstruction(''); }}>
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                    </button>
                  </div>
                </form>
              ) : (
                <form onSubmit={handleApplyChange} className="popover-form">
                  <textarea
                    ref={replaceInputRef}
                    placeholder="Replace with..."
                    value={replaceText}
                    onChange={(e) => setReplaceText(e.target.value)}
                    rows={1}
                    onInput={(e) => { e.target.style.height = 'auto'; e.target.style.height = e.target.scrollHeight + 'px'; }}
                  />
                  <div className="popover-form-actions">
                    <button type="submit" disabled={applying || !replaceText}>
                      {applying ? '...' : 'Replace'}
                    </button>
                    <button type="button" className="popover-cancel" onClick={() => { setPopoverMode(null); setReplaceText(''); }}>
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                    </button>
                  </div>
                </form>
              )}
            </div>
          )}
        </div>

        {/* Side panel: find results or changes */}
        {(occurrences || showChanges) && (
          <div className="doc-panel">
            {occurrences && (
              <div className="panel-section">
                <div className="panel-header">
                  <h3>Find Results</h3>
                  <span className="panel-count">{occurrenceTotal}</span>
                  <button className="panel-close" onClick={handleClearSearch}>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                  </button>
                </div>

                {occurrenceTotal > 0 && (
                  <div className="replace-all-section">
                    <div className="replace-all-input">
                      <input
                        type="text"
                        placeholder="Replace with..."
                        value={replaceAllText}
                        onChange={(e) => setReplaceAllText(e.target.value)}
                      />
                      <button
                        className="replace-all-btn"
                        disabled={applyingReplaceAll || occurrenceTotal === 0 || !replaceAllText}
                        onClick={handleReplaceAll}
                      >
                        {applyingReplaceAll ? 'Applying...' : `Replace All (${occurrenceTotal})`}
                      </button>
                    </div>
                  </div>
                )}

                {occurrenceTotal === 0 ? (
                  <p className="panel-empty">No matches found.</p>
                ) : (
                  <ul className="search-results-list">
                    {occurrences.matches.map((m, i) => (
                      <li
                        key={i}
                        className="search-result"
                        onClick={() => handleSearchResultClick(m.chunk_id, m.chunk_position)}
                      >
                        <div className="search-snippet">{m.snippet}</div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            {showChanges && (
              <div className="panel-section">
                <div className="panel-header">
                  <h3>Changes</h3>
                  <span className="panel-count">{allChanges.length}</span>
                  <button className="panel-close" onClick={() => setShowChanges(false)}>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                  </button>
                </div>

                {allChanges.length === 0 ? (
                  <p className="panel-empty">No changes yet.</p>
                ) : (
                  <>
                    {/* Pending changes with accept/reject */}
                    {pendingChanges.length > 0 && (
                      <div className="panel-subsection">
                        <div className="panel-subheader">Pending ({pendingChanges.length})</div>
                        <ul className="history-list">
                          {(() => {
                            // Group pending changes by change_group_id
                            const groups = new Map();
                            const ungrouped = [];
                            for (const c of pendingChanges) {
                              if (c.change_group_id) {
                                if (!groups.has(c.change_group_id)) groups.set(c.change_group_id, []);
                                groups.get(c.change_group_id).push(c);
                              } else {
                                ungrouped.push(c);
                              }
                            }
                            const items = [];
                            for (const [groupId, gChanges] of groups) {
                              items.push({ type: gChanges.length > 1 ? 'group' : 'single', groupId, changes: gChanges, created_at: gChanges[0].created_at });
                            }
                            for (const c of ungrouped) {
                              items.push({ type: 'single', changes: [c], created_at: c.created_at });
                            }
                            items.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

                            return items.map((item) => {
                              if (item.type === 'group') {
                                return (
                                  <li key={item.groupId} className="history-item history-item-group"
                                    onMouseEnter={() => setHighlightedGroupId(item.groupId)}
                                    onMouseLeave={() => setHighlightedGroupId(null)}
                                  >
                                    <div className="history-group-label">Grouped change ({item.changes.length} sections)</div>
                                    {item.changes.map((c) => (
                                      <div key={c.id} className="history-desc">
                                        {c.new_text === '' ? (
                                          <>delete <span className="diff-del">{c.old_text}</span></>
                                        ) : (
                                          <><span className="diff-del">{c.old_text}</span> to <span className="diff-ins">{c.new_text}</span></>
                                        )}
                                      </div>
                                    ))}
                                    <div className="panel-change-actions">
                                      <button className="panel-accept-btn" onClick={() => handleAccept(item.changes[0].id)}>Accept All</button>
                                      <button className="panel-reject-btn" onClick={() => handleReject(item.changes[0].id)}>Reject All</button>
                                    </div>
                                    <time className="history-time">{timeAgo(item.created_at)}</time>
                                  </li>
                                );
                              }
                              const c = item.changes[0];
                              return (
                                <li key={c.id} className="history-item">
                                  <div className="history-desc">
                                    {c.new_text === '' ? (
                                      <>delete <span className="diff-del">{c.old_text}</span></>
                                    ) : (
                                      <><span className="diff-del">{c.old_text}</span> to <span className="diff-ins">{c.new_text}</span></>
                                    )}
                                  </div>
                                  <div className="panel-change-actions">
                                    <button className="panel-accept-btn" onClick={() => handleAccept(c.id)}>Accept</button>
                                    <button className="panel-reject-btn" onClick={() => handleReject(c.id)}>Reject</button>
                                  </div>
                                  <time className="history-time">{timeAgo(c.created_at)}</time>
                                </li>
                              );
                            });
                          })()}
                        </ul>
                      </div>
                    )}

                    {/* Resolved changes */}
                    {resolvedChanges.length > 0 && (
                      <div className="panel-subsection">
                        {pendingChanges.length > 0 && <div className="panel-subheader">Resolved ({resolvedChanges.length})</div>}
                        <ul className="history-list">
                          {[...resolvedChanges].reverse().map((c) => (
                            <li key={c.id} className="history-item">
                              <div className="history-desc">
                                <span className={`history-status history-status-${c.status}`}>{c.status}</span>
                                {c.new_text === '' ? (
                                  <>{' '}delete <span className="diff-del">{c.old_text}</span></>
                                ) : (
                                  <>{' '}<span className="diff-del">{c.old_text}</span> to <span className="diff-ins">{c.new_text}</span></>
                                )}
                              </div>
                              <time className="history-time">{timeAgo(c.created_at)}</time>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
