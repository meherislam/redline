import { useState } from 'react';
import Sidebar from './components/Sidebar';
import DocumentList from './pages/DocumentList';
import DocumentView from './pages/DocumentView';
import './App.css';

function App() {
  const [selectedDocId, setSelectedDocId] = useState(null);
  const [highlightChunkId, setHighlightChunkId] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);

  function handleDocumentCreated() {
    setRefreshKey((k) => k + 1);
  }

  function handleSearchResultClick(documentId, chunkId) {
    setHighlightChunkId(chunkId);
    setSelectedDocId(documentId);
  }

  function handleBackToList() {
    setSelectedDocId(null);
    setHighlightChunkId(null);
  }

  return (
    <div className="app-layout">
      <Sidebar
        selectedId={selectedDocId}
        onSelect={(id) => { setSelectedDocId(id); setHighlightChunkId(null); }}
        onBackToList={handleBackToList}
        refreshKey={refreshKey}
        onDocumentCreated={handleDocumentCreated}
      />
      <main className="main-content">
        {selectedDocId ? (
          <DocumentView
            key={`${selectedDocId}-${highlightChunkId}`}
            documentId={selectedDocId}
            initialHighlightChunkId={highlightChunkId}
            onBack={handleBackToList}
          />
        ) : (
          <DocumentList
            refreshKey={refreshKey}
            onSelectDocument={(id) => { setSelectedDocId(id); setHighlightChunkId(null); }}
            onSearchResultClick={handleSearchResultClick}
            onDocumentCreated={handleDocumentCreated}
          />
        )}
      </main>
    </div>
  );
}

export default App;
