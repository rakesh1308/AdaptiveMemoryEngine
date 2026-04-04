/**
 * ChunkStore - Manages content chunking with multiple strategies
 * Handles chunk storage, retrieval, and embedding coordination
 */

import crypto from 'crypto';
import { EventBus, MemoryEvents } from '../infrastructure/EventBus.js';

export class ChunkingStrategies {
  /**
   * Fixed-size chunking with overlap
   */
  static fixed(content, options = {}) {
    const chunkSize = options.chunkSize || 2500;
    const overlap = options.overlap || 250;
    const chunks = [];
    let start = 0;
    let index = 0;
    
    while (start < content.length) {
      const end = Math.min(start + chunkSize, content.length);
      chunks.push({
        index: index++,
        content: content.slice(start, end),
        start,
        end
      });
      
      if (end === content.length) break;
      start = end - overlap;
    }
    
    return chunks;
  }

  /**
   * Paragraph-based chunking (natural boundaries)
   */
  static paragraph(content, options = {}) {
    const maxChunkSize = options.maxChunkSize || 2500;
    const paragraphs = content.split(/\n\s*\n/);
    const chunks = [];
    let currentChunk = '';
    let index = 0;
    
    for (const paragraph of paragraphs) {
      if ((currentChunk + paragraph).length > maxChunkSize && currentChunk.length > 0) {
        chunks.push({
          index: index++,
          content: currentChunk.trim(),
          start: 0, // Would need proper tracking
          end: 0
        });
        currentChunk = paragraph;
      } else {
        currentChunk += (currentChunk ? '\n\n' : '') + paragraph;
      }
    }
    
    if (currentChunk.trim()) {
      chunks.push({
        index: index++,
        content: currentChunk.trim(),
        start: 0,
        end: 0
      });
    }
    
    return chunks;
  }

  /**
   * Semantic chunking (preserves semantic boundaries)
   * Uses headings, sections, and natural breaks
   */
  static semantic(content, options = {}) {
    const maxChunkSize = options.maxChunkSize || 2500;
    
    // Split on headings, code blocks, and paragraph boundaries
    const sections = content.split(/(?=^#{1,6}\s|^```|^\n#{1,6}\s)/m);
    const chunks = [];
    let index = 0;
    
    for (const section of sections) {
      if (section.length > maxChunkSize) {
        // Subdivide large sections
        const subChunks = ChunkingStrategies.fixed(section, { chunkSize: maxChunkSize, overlap: 250 });
        for (const sub of subChunks) {
          chunks.push({ ...sub, index: index++ });
        }
      } else if (section.trim()) {
        chunks.push({
          index: index++,
          content: section.trim(),
          start: 0,
          end: 0
        });
      }
    }
    
    return chunks;
  }

  /**
   * Hierarchical chunking (parent-child relationships)
   */
  static hierarchical(content, options = {}) {
    const chunks = ChunkingStrategies.semantic(content, options);
    const hierarchy = [];
    let parentStack = [];
    
    for (const chunk of chunks) {
      const headingMatch = chunk.content.match(/^(#{1,6})\s/);
      const level = headingMatch ? headingMatch[1].length : 6;
      
      // Adjust parent stack based on heading level
      parentStack = parentStack.filter(p => p.level < level);
      
      hierarchy.push({
        ...chunk,
        parent: parentStack.length > 0 ? parentStack[parentStack.length - 1].index : null,
        level
      });
      
      if (headingMatch) {
        parentStack.push({ index: chunk.index, level });
      }
    }
    
    return hierarchy;
  }
}

export class ChunkStore {
  constructor(options = {}) {
    this.chunks = new Map(); // chunkId -> chunk
    this.memoryChunks = new Map(); // memoryId -> chunkIds[]
    this.eventBus = options.eventBus || new EventBus();
    this.defaultStrategy = options.strategy || 'semantic';
    this.defaultOptions = options.chunkOptions || {};
  }

  /**
   * Chunk content using specified strategy
   */
  chunk(content, strategy = null, options = {}) {
    const strat = strategy || this.defaultStrategy;
    const opts = { ...this.defaultOptions, ...options };
    
    const chunker = ChunkingStrategies[strat];
    if (!chunker) {
      throw new Error(`Unknown chunking strategy: ${strat}`);
    }
    
    return chunker(content, opts);
  }

  /**
   * Store chunks for a memory
   */
  async storeChunks(memoryId, content, strategy = null, options = {}) {
    const rawChunks = this.chunk(content, strategy, options);
    const chunkIds = [];
    const storedChunks = [];
    
    for (const raw of rawChunks) {
      const chunkId = `${memoryId}__${raw.index}`;
      const chunk = {
        id: chunkId,
        memoryId,
        index: raw.index,
        content: raw.content,
        hash: this.computeHash(raw.content),
        createdAt: new Date().toISOString(),
        embedding: null,
        parent: raw.parent || null,
        level: raw.level || 0,
        metadata: {
          start: raw.start,
          end: raw.end,
          charCount: raw.content.length,
          wordCount: raw.content.split(/\s+/).length
        }
      };
      
      this.chunks.set(chunkId, chunk);
      chunkIds.push(chunkId);
      storedChunks.push(chunk);
    }
    
    this.memoryChunks.set(memoryId, chunkIds);
    
    // Emit events
    for (const chunk of storedChunks) {
      await this.eventBus.publish(MemoryEvents.CHUNK_CREATED, { chunk });
    }
    
    return storedChunks;
  }

  /**
   * Get chunk by ID
   */
  getChunk(chunkId) {
    return this.chunks.get(chunkId);
  }

  /**
   * Get all chunks for a memory
   */
  getMemoryChunks(memoryId) {
    const chunkIds = this.memoryChunks.get(memoryId) || [];
    return chunkIds.map(id => this.chunks.get(id)).filter(Boolean);
  }

  /**
   * Get chunks in order
   */
  getOrderedChunks(memoryId) {
    return this.getMemoryChunks(memoryId).sort((a, b) => a.index - b.index);
  }

  /**
   * Update chunk embedding
   */
  async setEmbedding(chunkId, embedding) {
    const chunk = this.chunks.get(chunkId);
    if (!chunk) {
      throw new Error(`Chunk not found: ${chunkId}`);
    }
    
    chunk.embedding = embedding;
    chunk.updatedAt = new Date().toISOString();
    
    await this.eventBus.publish(MemoryEvents.CHUNK_EMBEDDED, {
      chunkId,
      memoryId: chunk.memoryId,
      vectorSize: embedding?.length
    });
    
    return chunk;
  }

  /**
   * Find similar chunks by embedding
   */
  findSimilar(embedding, options = {}) {
    const topK = options.topK || 5;
    const excludeMemoryId = options.excludeMemoryId;
    
    const scores = [];
    
    for (const chunk of this.chunks.values()) {
      if (!chunk.embedding) continue;
      if (excludeMemoryId && chunk.memoryId === excludeMemoryId) continue;
      
      const similarity = this.cosineSimilarity(embedding, chunk.embedding);
      scores.push({ chunk, similarity });
    }
    
    return scores
      .sort((a, b) => b.similarity - a.similarity)
      .slice(0, topK);
  }

  /**
   * Get best chunks for a query (requires embeddings)
   */
  async getBestChunks(memoryId, queryEmbedding, topN = 4) {
    const chunks = this.getMemoryChunks(memoryId);
    
    if (chunks.length === 0) {
      return [];
    }
    
    if (!queryEmbedding) {
      return chunks.slice(0, topN);
    }
    
    return chunks
      .filter(c => c.embedding)
      .map(c => ({
        chunk: c,
        score: this.cosineSimilarity(queryEmbedding, c.embedding)
      }))
      .sort((a, b) => b.score - a.score)
      .slice(0, topN)
      .map(x => x.chunk);
  }

  /**
   * Delete all chunks for a memory
   */
  deleteMemoryChunks(memoryId) {
    const chunkIds = this.memoryChunks.get(memoryId) || [];
    let deleted = 0;
    
    for (const id of chunkIds) {
      if (this.chunks.delete(id)) {
        deleted++;
      }
    }
    
    this.memoryChunks.delete(memoryId);
    return deleted;
  }

  /**
   * Get chunk statistics
   */
  getStats() {
    const chunks = Array.from(this.chunks.values());
    const withEmbeddings = chunks.filter(c => c.embedding).length;
    
    return {
      totalChunks: chunks.length,
      embeddedChunks: withEmbeddings,
      embeddingCoverage: chunks.length > 0 ? (withEmbeddings / chunks.length) : 0,
      memoriesWithChunks: this.memoryChunks.size,
      avgChunksPerMemory: this.memoryChunks.size > 0 
        ? (chunks.length / this.memoryChunks.size).toFixed(2)
        : 0,
      avgChunkSize: chunks.length > 0
        ? (chunks.reduce((sum, c) => sum + c.content.length, 0) / chunks.length).toFixed(0)
        : 0
    };
  }

  /**
   * Export all chunks
   */
  export() {
    return {
      chunks: Array.from(this.chunks.entries()),
      memoryChunks: Array.from(this.memoryChunks.entries())
    };
  }

  /**
   * Import chunks
   */
  import(data) {
    this.chunks = new Map(data.chunks);
    this.memoryChunks = new Map(data.memoryChunks);
  }

  computeHash(content) {
    return crypto.createHash('sha256').update(content).digest('hex').slice(0, 16);
  }

  cosineSimilarity(a, b) {
    if (!a || !b || a.length !== b.length) return 0;
    
    let dot = 0, normA = 0, normB = 0;
    for (let i = 0; i < a.length; i++) {
      dot += a[i] * b[i];
      normA += a[i] * a[i];
      normB += b[i] * b[i];
    }
    
    return dot / (Math.sqrt(normA) * Math.sqrt(normB));
  }
}
