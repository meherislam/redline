import { useEffect, useState, useRef } from 'react';
import { listDocuments, createDocument, search as apiSearch } from '../api/client';

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

function groupResultsByDocument(results) {
  const groups = {};
  for (const r of results) {
    if (!groups[r.document_id]) {
      groups[r.document_id] = {
        document_id: r.document_id,
        document_title: r.document_title,
        results: [],
      };
    }
    groups[r.document_id].results.push(r);
  }
  return Object.values(groups);
}

export default function DocumentList({ refreshKey, onSelectDocument, onSearchResultClick, onDocumentCreated }) {
  const [documents, setDocuments] = useState([]);
  const [error, setError] = useState(null);

  // Upload
  const [showUpload, setShowUpload] = useState(false);
  const [title, setTitle] = useState('');
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef(null);

  // Search
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState(null);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    listDocuments()
      .then((data) => setDocuments(data.documents))
      .catch((e) => setError(e.message));
  }, [refreshKey]);

  async function handleUpload(e) {
    e.preventDefault();
    if (!title.trim() || !file) return;
    setUploading(true);
    setError(null);
    try {
      const created = await createDocument(title.trim(), file);
      setTitle('');
      setFile(null);
      setShowUpload(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
      onDocumentCreated();
      onSelectDocument(created.id);
    } catch (err) {
      setError(err.message);
    } finally {
      setUploading(false);
    }
  }

  async function handleSearch(e) {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    setSearching(true);
    setError(null);
    try {
      const data = await apiSearch(searchQuery.trim());
      setSearchResults(data.results);
    } catch (err) {
      setError(err.message);
    } finally {
      setSearching(false);
    }
  }

  function clearSearch() {
    setSearchQuery('');
    setSearchResults(null);
  }

  const grouped = searchResults ? groupResultsByDocument(searchResults) : null;

  return (
    <div className="doclist-page">
      <div className="doclist-header">
        <div className="doclist-header-top">
          <h1 className="doclist-heading">Documents</h1>
          <button
            className="doclist-upload-btn"
            onClick={() => setShowUpload(!showUpload)}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
            Upload
          </button>
        </div>

        {showUpload && (
          <form onSubmit={handleUpload} className="doclist-upload-form">
            <input
              type="text"
              placeholder="Document title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              autoFocus
            />
            <label className="doclist-file-drop">
              <input
                ref={fileInputRef}
                type="file"
                accept=".txt"
                onChange={(e) => setFile(e.target.files[0])}
              />
              <span>{file ? file.name : 'Choose a .txt file'}</span>
            </label>
            <div className="doclist-upload-actions">
              <button type="button" className="btn-secondary" onClick={() => setShowUpload(false)}>Cancel</button>
              <button type="submit" className="btn-primary" disabled={uploading || !title.trim() || !file}>
                {uploading ? 'Uploading...' : 'Upload'}
              </button>
            </div>
          </form>
        )}

        <form onSubmit={handleSearch} className="doclist-search">
          <svg className="doclist-search-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input
            type="text"
            placeholder="Search across all documents..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          {searchQuery && (
            <button type="button" className="doclist-search-clear" onClick={clearSearch}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          )}
        </form>
      </div>

      {error && (
        <div className="toast toast-error" style={{ margin: '0 0 16px' }}>
          <span>{error}</span>
          <button onClick={() => setError(null)}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
      )}

      <div className="doclist-body">
        {searchResults !== null ? (
          /* Search results view */
          <div className="search-results-view">
            <div className="search-results-header">
              <span className="search-results-summary">
                {searchResults.length === 0
                  ? 'No results found'
                  : `${searchResults.length} result${searchResults.length === 1 ? '' : 's'} across ${grouped.length} document${grouped.length === 1 ? '' : 's'}`
                }
              </span>
              <button className="btn-link" onClick={clearSearch}>Clear search</button>
            </div>

            {grouped.map((group) => (
              <div key={group.document_id} className="search-group">
                <div className="search-group-header" onClick={() => onSelectDocument(group.document_id)}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                  </svg>
                  <span className="search-group-title">{group.document_title}</span>
                  <span className="search-group-count">
                    {group.results.length} match{group.results.length === 1 ? '' : 'es'}
                  </span>
                </div>
                <ul className="search-group-results">
                  {group.results.map((r, i) => (
                    <li
                      key={i}
                      className="search-group-result"
                      onClick={() => onSearchResultClick(r.document_id, r.chunk_id, r.chunk_position)}
                    >
                      <div className="search-snippet" dangerouslySetInnerHTML={{ __html: r.snippet }} />
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        ) : documents.length === 0 ? (
          /* Empty state */
          <div className="doclist-empty">
            <div className="doclist-empty-icon">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="16" y1="13" x2="8" y2="13" />
                <line x1="16" y1="17" x2="8" y2="17" />
              </svg>
            </div>
            <p>No documents yet. Upload one to get started.</p>
          </div>
        ) : (
          /* Document table */
          <table className="doclist-table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Last modified</th>
              </tr>
            </thead>
            <tbody>
              {documents.map((doc) => (
                <tr key={doc.id} onClick={() => onSelectDocument(doc.id)}>
                  <td>
                    <div className="doclist-table-title">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                        <polyline points="14 2 14 8 20 8" />
                      </svg>
                      {doc.title}
                    </div>
                  </td>
                  <td className="doclist-table-meta">{timeAgo(doc.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
