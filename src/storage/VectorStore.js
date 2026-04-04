/**
 * VectorStore - Manages embeddings and similarity search
 * Supports multiple backends: in-memory, HNSW, or external vector DB
 */

import { EventBus, MemoryEvents } from '../infrastructure/EventBus.js';

export class VectorStore {
  constructor(options = {}) {
    this.backend = options.backend || 'memory'; // 'memory', 'hnsw', 'external'
    this.dimensions = options.dimensions || 1536; // OpenAI embedding size
    this.vectors = new Map(); // id -> { id, vector, metadata }
    this.index = null; // Would be HNSW index for larger datasets
    this.eventBus = options.eventBus || new EventBus();
    
    this.embeddingProvider = options.embeddingProvider;
    this.cacheEmbeddings = options.cacheEmbeddings !== false;
    this.embeddingCache = new Map();
  }

  /**
   * Get embedding for text
   */
  async embed(text) {
    const cacheKey = this.hashText(text);
    
    if (this.cacheEmbeddings && this.embeddingCache.has(cacheKey)) {
      return this.embeddingCache.get(cacheKey);
    }
    
    if (!this.embeddingProvider) {
      throw new Error('No embedding provider configured');
    }
    
    const embedding = await this.embeddingProvider.embed(text);
    
    if (this.cacheEmbeddings) {
      this.embeddingCache.set(cacheKey, embedding);
      
      // Limit cache size
      if (this.embeddingCache.size > 10000) {
        const firstKey = this.embeddingCache.keys().next().value;
        this.embeddingCache.delete(firstKey);
      }
    }
    
    return embedding;
  }

  /**
   * Get embeddings for multiple texts (batch)
   */
  async embedBatch(texts) {
    if (!this.embeddingProvider) {
      throw new Error('No embedding provider configured');
    }
    
    return this.embeddingProvider.embedBatch(texts);
  }

  /**
   * Store a vector
   */
  async store(id, vector, metadata = {}) {
    this.vectors.set(id, {
      id,
      vector,
      metadata,
      createdAt: new Date().toISOString()
    });
    
    await this.eventBus.publish(MemoryEvents.CHUNK_EMBEDDED, {
      chunkId: id,
      vectorSize: vector.length
    });
  }

  /**
   * Store multiple vectors
   */
  async storeBatch(items) {
    for (const { id, vector, metadata } of items) {
      await this.store(id, vector, metadata);
    }
  }

  /**
   * Get vector by ID
   */
  get(id) {
    return this.vectors.get(id);
  }

  /**
   * Delete vector
   */
  delete(id) {
    return this.vectors.delete(id);
  }

  /**
   * Delete all vectors for a memory
   */
  deleteByMemoryId(memoryId) {
    const toDelete = [];
    
    for (const [id, item] of this.vectors) {
      if (item.metadata.memoryId === memoryId) {
        toDelete.push(id);
      }
    }
    
    for (const id of toDelete) {
      this.vectors.delete(id);
    }
    
    return toDelete.length;
  }

  /**
   * Search by vector similarity
   */
  search(queryVector, options = {}) {
    const topK = options.topK || 10;
    const filter = options.filter || null;
    const minScore = options.minScore || 0;
    
    const results = [];
    
    for (const [id, item] of this.vectors) {
      // Apply filter if provided
      if (filter && !filter(item.metadata)) continue;
      
      const score = this.cosineSimilarity(queryVector, item.vector);
      
      if (score >= minScore) {
        results.push({
          id,
          score,
          metadata: item.metadata
        });
      }
    }
    
    return results
      .sort((a, b) => b.score - a.score)
      .slice(0, topK);
  }

  /**
   * Search by text (auto-embeds query)
   */
  async searchByText(queryText, options = {}) {
    const queryVector = await this.embed(queryText);
    return this.search(queryVector, options);
  }

  /**
   * Hybrid search: combine vector + keyword scores
   */
  async hybridSearch(queryText, queryVector, keywordResults, options = {}) {
    const semanticWeight = options.semanticWeight || 0.7;
    const keywordWeight = options.keywordWeight || 0.3;
    const topK = options.topK || 10;
    
    // Get semantic results
    const semanticResults = this.search(queryVector, { topK: topK * 2 });
    
    // Create score maps
    const semanticMap = new Map(semanticResults.map(r => [r.id, r.score]));
    const keywordMap = new Map(keywordResults.map(r => [r.id, r.score]));
    
    // Combine all IDs
    const allIds = new Set([
      ...semanticMap.keys(),
      ...keywordMap.keys()
    ]);
    
    // Calculate hybrid scores
    const results = [];
    for (const id of allIds) {
      const semanticScore = semanticMap.get(id) || 0;
      const keywordScore = keywordMap.get(id) || 0;
      
      const hybridScore = 
        semanticWeight * semanticScore + 
        keywordWeight * keywordScore;
      
      results.push({
        id,
        hybridScore,
        semanticScore,
        keywordScore,
        metadata: this.vectors.get(id)?.metadata
      });
    }
    
    return results
      .sort((a, b) => b.hybridScore - a.hybridScore)
      .slice(0, topK);
  }

  /**
   * Find similar vectors to a given ID
   */
  findSimilar(id, options = {}) {
    const item = this.vectors.get(id);
    if (!item) return [];
    
    const results = this.search(item.vector, { ...options, topK: (options.topK || 5) + 1 });
    
    // Exclude the query itself
    return results.filter(r => r.id !== id);
  }

  /**
   * Rebuild the search index
   */
  async rebuildIndex() {
    console.log('[VectorStore] Rebuilding index...');
    
    if (this.backend === 'hnsw') {
      // Rebuild HNSW index
      // this.index = new HNSW(this.dimensions);
      // for (const [id, item] of this.vectors) {
      //   this.index.addPoint(item.vector, id);
      // }
    }
    
    console.log(`[VectorStore] Index rebuilt with ${this.vectors.size} vectors`);
  }

  /**
   * Get statistics
   */
  getStats() {
    return {
      totalVectors: this.vectors.size,
      dimensions: this.dimensions,
      backend: this.backend,
      cacheSize: this.embeddingCache.size
    };
  }

  /**
   * Export all vectors
   */
  export() {
    return Array.from(this.vectors.entries());
  }

  /**
   * Import vectors
   */
  import(data) {
    this.vectors = new Map(data);
  }

  cosineSimilarity(a, b) {
    if (!a || !b || a.length !== b.length) return 0;
    
    let dot = 0, normA = 0, normB = 0;
    for (let i = 0; i < a.length; i++) {
      dot += a[i] * b[i];
      normA += a[i] * a[i];
      normB += b[i] * b[i];
    }
    
    return normA === 0 || normB === 0 ? 0 : dot / (Math.sqrt(normA) * Math.sqrt(normB));
  }

  hashText(text) {
    // Simple hash for caching
    let hash = 0;
    for (let i = 0; i < text.length; i++) {
      const char = text.charCodeAt(i);
      hash = ((hash << 5) - hash) + char;
      hash = hash & hash;
    }
    return hash.toString(36);
  }
}
