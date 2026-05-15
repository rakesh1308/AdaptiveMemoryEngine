/**
 * MemoryEngine - The core orchestrator of the memory system
 * Coordinates storage, intelligence, lifecycle, and search
 * 
 * Requirements:
 * - embeddingProvider is MANDATORY
 * - intelligenceProvider is OPTIONAL (for AI-enhanced tags, ask, summarize, graph)
 * - SQLite is the ONLY storage backend
 */

import fs from 'fs';
import path from 'path';
import { EventBus, MemoryEvents } from '../infrastructure/EventBus.js';
import { TransactionManager } from './TransactionManager.js';
import { ChunkStore } from './ChunkStore.js';
import { KnowledgeGraph } from '../intelligence/KnowledgeGraph.js';
import { MemoryLifecycle } from '../lifecycle/MemoryLifecycle.js';
import { SQLiteBackend } from '../storage/backends/SQLiteBackend.js';
import { VectorStore } from '../storage/VectorStore.js';

export class MemoryEngine {
  constructor(options = {}) {
    this.options = options;
    this.dataDir = options.dataDir || './data';
    
    // Validate mandatory embedding provider
    if (!options.embeddingProvider) {
      throw new Error('[MemoryEngine] embeddingProvider is required. AdaptiveMemoryEngine requires semantic embeddings.');
    }
    if (!options.embeddingProvider.isAvailable || !options.embeddingProvider.isAvailable()) {
      throw new Error('[MemoryEngine] embeddingProvider is not available. Check your API key and connectivity.');
    }
    
    this.embeddingProvider = options.embeddingProvider;
    this.intelligenceProvider = options.intelligenceProvider || null;
    
    // Initialize infrastructure
    this.eventBus = new EventBus();
    this.transactionManager = new TransactionManager({
      dataDir: this.dataDir,
      eventBus: this.eventBus
    });
    
    // Initialize storage - SQLite ONLY
    this.sqliteBackend = new SQLiteBackend({ dataDir: this.dataDir });
    this.sqliteAvailable = false;
    
    this.chunkStore = new ChunkStore({ eventBus: this.eventBus });
    this.vectorStore = new VectorStore({
      eventBus: this.eventBus,
      embeddingProvider: this.embeddingProvider
    });
    
    // Initialize intelligence
    this.knowledgeGraph = new KnowledgeGraph({
      eventBus: this.eventBus,
      dataDir: this.dataDir,
      intelligenceProvider: this.intelligenceProvider
    });
    
    // Initialize lifecycle
    this.lifecycle = new MemoryLifecycle({
      eventBus: this.eventBus,
      archive: { dataDir: this.dataDir }
    });
    
    // In-memory cache
    this.memories = new Map();
    this.initialized = false;
    
    // Track which memories have been processed for knowledge graph
    this.graphProcessedMemories = new Set();
    this.graphStateFile = path.join(this.dataDir, 'graph-state.json');
  }

  async initialize() {
    if (this.initialized) return;
    
    console.error('[MemoryEngine] Initializing...');
    console.error(`[MemoryEngine] Data directory: ${this.dataDir}`);
    
    // Initialize SQLite (required)
    this.sqliteAvailable = await this.sqliteBackend.initialize();
    if (!this.sqliteAvailable) {
      throw new Error('[MemoryEngine] SQLite initialization failed. SQLite is the only supported storage backend.');
    }
    
    console.error('[MemoryEngine] SQLite initialized, loading data...');
    
    // Load from SQLite
    const memories = this.sqliteBackend.getAll();
    console.error(`[MemoryEngine] SQLite returned ${memories.length} memories`);
    
    this.memories = new Map(memories.map(m => [m.id, m]));
    console.error(`[MemoryEngine] In-memory cache has ${this.memories.size} memories`);
    
    // Load embeddings from SQLite
    const embeddings = this.sqliteBackend.getAllEmbeddings();
    console.error(`[MemoryEngine] SQLite returned ${embeddings.size} embeddings`);
    
    for (const [id, embedding] of embeddings) {
      this.vectorStore.vectors.set(id, {
        id,
        vector: embedding,
        metadata: { memoryId: id },
        createdAt: new Date().toISOString()
      });
    }
    
    console.error(`[MemoryEngine] Loaded ${this.memories.size} memories and ${embeddings.size} embeddings from SQLite`);
    
    // Common initialization steps
    await this.finishInitialization();
  }

  async finishInitialization() {
    // Normalize v2.0 format to v3.0
    let migrated = 0;
    for (const [id, memory] of this.memories) {
      const normalized = this.normalizeMemory(memory);
      if (normalized !== memory) {
        this.memories.set(id, normalized);
        migrated++;
      }
    }
    if (migrated > 0) {
      console.log(`[MemoryEngine] Migrated ${migrated} memories from v2.0 format`);
    }
    
    // Load graph state and knowledge graph
    await this.loadGraphState();
    const graphLoaded = await this.knowledgeGraph.load();
    
    if (this.graphProcessedMemories.size > 0 && !graphLoaded) {
      console.log('[MemoryEngine] WARNING: Graph state says processed but graph is empty. Resetting state.');
      this.graphProcessedMemories.clear();
    }
    
    // Build knowledge graph in background
    if (this.memories.size > 100) {
      const unprocessed = this.memories.size - this.graphProcessedMemories.size;
      console.log(`[MemoryEngine] Skipping bulk knowledge graph build (${this.memories.size} memories).`);
      console.log(`[MemoryEngine] ${unprocessed} memories need processing - will refill gracefully over time.`);
      this.startGracefulRefill();
    } else {
      this.buildKnowledgeGraphAsync().catch(err => {
        console.error('[MemoryEngine] Knowledge graph build failed:', err.message);
      });
    }
    
    this.initialized = true;
    console.log('[MemoryEngine] Initialized successfully');
  }

  normalizeMemory(memory) {
    const normalized = { ...memory };
    let changed = false;
    
    if (memory.created && !memory.createdAt) {
      normalized.createdAt = memory.created;
      changed = true;
    }
    if (memory.updated && !memory.updatedAt) {
      normalized.updatedAt = memory.updated;
      changed = true;
    }
    if (memory.importance === undefined) {
      normalized.importance = this.lifecycle?.importanceScorer?.calculate(memory) || 50;
      changed = true;
    }
    if (memory.strength === undefined) {
      normalized.strength = 1.0;
      changed = true;
    }
    if (memory.accessCount === undefined) {
      normalized.accessCount = 0;
      changed = true;
    }
    if (memory.version === undefined) {
      normalized.version = 1;
      changed = true;
    }
    
    return changed ? normalized : memory;
  }

  async buildKnowledgeGraphAsync() {
    await this.loadGraphState();
    
    const unprocessedMemories = Array.from(this.memories.values())
      .filter(m => !this.graphProcessedMemories.has(m.id));
    
    const total = unprocessedMemories.length;
    
    if (total === 0) {
      console.log('[MemoryEngine] Knowledge graph up to date');
      return;
    }
    
    console.log(`[MemoryEngine] Building knowledge graph for ${total} new memories...`);
    
    const BATCH_SIZE = 25;
    let processed = 0;
    let errors = 0;
    
    for (let i = 0; i < total; i += BATCH_SIZE) {
      const batch = unprocessedMemories.slice(i, i + BATCH_SIZE);
      
      for (const memory of batch) {
        try {
          await this.knowledgeGraph.buildFromMemory(
            memory.id,
            memory.content,
            memory.tags || []
          );
          this.graphProcessedMemories.add(memory.id);
          processed++;
        } catch (err) {
          errors++;
          console.error(`[MemoryEngine] Failed to process ${memory.id}: ${err.message}`);
        }
        
        if (processed % 100 === 0) {
          await this.saveGraphState();
        }
        
        await new Promise(resolve => setTimeout(resolve, 5));
      }
      
      console.log(`[MemoryEngine] Knowledge graph progress: ${processed}/${total}`);
    }
    
    await this.saveGraphState();
    
    const stats = this.knowledgeGraph.getStats();
    console.log(`[MemoryEngine] Knowledge graph complete: ${stats.concepts} concepts, ${stats.relationships} relationships (${errors} errors)`);
  }

  async loadGraphState() {
    try {
      if (fs.existsSync(this.graphStateFile)) {
        const data = JSON.parse(fs.readFileSync(this.graphStateFile, 'utf-8'));
        this.graphProcessedMemories = new Set(data.processed || []);
        console.log(`[MemoryEngine] Loaded graph state: ${this.graphProcessedMemories.size} memories processed`);
      }
    } catch (err) {
      console.log('[MemoryEngine] No existing graph state, starting fresh');
      this.graphProcessedMemories = new Set();
    }
  }

  async saveGraphState() {
    try {
      const data = {
        processed: Array.from(this.graphProcessedMemories),
        updatedAt: new Date().toISOString()
      };
      fs.writeFileSync(this.graphStateFile, JSON.stringify(data));
    } catch (err) {
      console.error('[MemoryEngine] Failed to save graph state:', err.message);
    }
  }

  startGracefulRefill() {
    const REFILL_INTERVAL = 60000;
    const BATCH_SIZE = 10;
    
    console.log(`[MemoryEngine] Starting graceful knowledge graph refill (${BATCH_SIZE} memories every ${REFILL_INTERVAL/1000}s)`);
    
    const processBatch = async () => {
      try {
        const unprocessed = Array.from(this.memories.values())
          .filter(m => !this.graphProcessedMemories.has(m.id));
        
        if (unprocessed.length === 0) {
          console.log('[MemoryEngine] Graceful refill complete!');
          return;
        }
        
        const batch = unprocessed.slice(0, BATCH_SIZE);
        console.log(`[MemoryEngine] Graceful refill: Processing ${batch.length} memories (${unprocessed.length - batch.length} remaining)`);
        
        let processed = 0;
        let errors = 0;
        
        for (const memory of batch) {
          try {
            await this.knowledgeGraph.buildFromMemory(
              memory.id,
              memory.content,
              memory.tags || []
            );
            this.graphProcessedMemories.add(memory.id);
            processed++;
          } catch (err) {
            errors++;
            if (errors <= 3) {
              console.error(`[MemoryEngine] Failed to process ${memory.id}: ${err.message}`);
            }
          }
          await new Promise(resolve => setTimeout(resolve, 100));
        }
        
        await this.saveGraphState();
        
        const stats = this.knowledgeGraph.getStats();
        console.log(`[MemoryEngine] Graceful refill batch complete: +${processed} memories, ${stats.concepts} total concepts`);
        
        setTimeout(processBatch, REFILL_INTERVAL);
      } catch (err) {
        console.error('[MemoryEngine] Graceful refill error:', err.message);
        setTimeout(processBatch, REFILL_INTERVAL * 2);
      }
    };
    
    setTimeout(processBatch, 5000);
  }

  async storeMemory(key, content, options = {}) {
    const { tags = [], autoTag = true, source = 'user' } = options;
    
    return this.transactionManager.run(async (tx) => {
      // Auto-tag if enabled and no tags provided
      let finalTags = tags;
      if (autoTag && tags.length === 0 && this.intelligenceProvider?.autoTag) {
        try {
          finalTags = await this.intelligenceProvider.autoTag(key, content);
        } catch (e) {
          finalTags = [];
        }
      }
      
      const now = new Date().toISOString();
      const memory = {
        id: key,
        content,
        tags: finalTags,
        source,
        createdAt: now,
        updatedAt: now,
        accessCount: 0,
        importance: 50,
        strength: 1.0,
        version: 1
      };
      
      memory.importance = this.lifecycle.importanceScorer.calculate(memory);
      
      tx.addOperation('store', memory, async (data) => {
        this.memories.delete(data.id);
        this.chunkStore.deleteMemoryChunks(data.id);
        this.vectorStore.deleteByMemoryId(data.id);
        this.sqliteBackend.delete(data.id);
      });
      
      // Chunk content
      const chunks = await this.chunkStore.storeChunks(
        memory.id,
        memory.content,
        options.chunkStrategy
      );
      
      // Store to SQLite first (required before embedding FK)
      this.memories.set(memory.id, memory);
      this.sqliteBackend.insert(memory);
      
      // Generate embeddings (MANDATORY)
      const chunkTexts = chunks.map(c => c.content);
      const embeddings = await this.vectorStore.embedBatch(chunkTexts);
      
      for (let i = 0; i < chunks.length; i++) {
        if (embeddings[i]) {
          await this.vectorStore.store(
            chunks[i].id,
            embeddings[i],
            { memoryId: memory.id, chunkIndex: chunks[i].index }
          );
          await this.chunkStore.setEmbedding(chunks[i].id, embeddings[i]);
          this.sqliteBackend.saveEmbedding(memory.id, embeddings[i]);
        }
      }
      
      // Build knowledge graph
      await this.knowledgeGraph.buildFromMemory(memory.id, memory.content, memory.tags);
      this.graphProcessedMemories.add(memory.id);
      
      if (this.graphProcessedMemories.size % 10 === 0) {
        await this.saveGraphState();
      }
      
      await this.eventBus.publish(MemoryEvents.MEMORY_CREATED, {
        memoryId: memory.id,
        chunks: chunks.length,
        tags: memory.tags
      });
      
      return {
        memory,
        chunks: chunks.length,
        tags: memory.tags
      };
    });
  }

  async recallMemory(key, context = {}) {
    let memory = this.sqliteBackend.get(key);
    
    if (!memory) {
      memory = this.memories.get(key);
    }
    
    if (!memory) {
      return null;
    }
    
    await this.lifecycle.recordAccess(memory, context);
    
    this.sqliteBackend.update(key, {
      accessCount: memory.accessCount + 1,
      updatedAt: new Date().toISOString()
    });
    
    this.memories.set(key, memory);
    
    return memory;
  }

  async searchMemories(query, options = {}) {
    const { topK = 10, mode = 'hybrid', filter = null } = options;
    
    let results = [];
    
    // SQLite FTS for keyword component
    if (mode === 'keyword' || mode === 'hybrid') {
      const sqliteResults = this.sqliteBackend.search(query, { limit: topK * 2 });
      if (sqliteResults.length > 0) {
        results = sqliteResults.map(m => ({
          memory: m,
          score: 1.0,
          method: 'sqlite-fts'
        }));
      }
    }
    
    // Fallback to in-memory keyword search
    if (results.length === 0) {
      results = this.keywordSearch(query, { topK: topK * 2 });
    }
    
    // Semantic search (MANDATORY - always available)
    if (mode === 'semantic' || mode === 'hybrid') {
      try {
        const queryVector = await this.vectorStore.embed(query);
        
        if (mode === 'semantic') {
          const semanticResults = this.vectorStore.search(queryVector, { topK });
          results = semanticResults
            .filter(r => r.metadata?.memoryId)
            .map(r => ({
              memory: this.memories.get(r.metadata.memoryId),
              score: r.score,
              method: 'semantic'
            })).filter(r => r.memory);
        } else {
          const hybridResults = await this.vectorStore.hybridSearch(
            query,
            queryVector,
            results.map(r => ({ id: r.memory.id, score: r.score / 100 })),
            { topK, semanticWeight: 0.7, keywordWeight: 0.3 }
          );
          results = hybridResults
            .filter(r => r.metadata?.memoryId)
            .map(r => ({
              memory: this.memories.get(r.metadata.memoryId),
              score: r.hybridScore,
              semanticScore: r.semanticScore,
              keywordScore: r.keywordScore,
              method: 'hybrid'
            })).filter(r => r.memory);
        }
      } catch (e) {
        console.log('[MemoryEngine] Semantic search failed:', e.message);
      }
    }
    
    if (mode === 'graph') {
      const concepts = this.knowledgeGraph.extractConcepts(query);
      const memoryIds = this.knowledgeGraph.findMemoriesByConcepts(concepts, false);
      results = memoryIds.map(id => ({
        memory: this.memories.get(id),
        score: 1.0,
        method: 'graph'
      })).filter(r => r.memory);
    }
    
    if (filter) {
      results = results.filter(r => filter(r.memory));
    }
    
    for (const result of results.slice(0, 3)) {
      await this.lifecycle.recordAccess(result.memory, { query, source: 'search' });
    }
    
    return results.slice(0, topK);
  }

  keywordSearch(query, options = {}) {
    const tokens = query.toLowerCase().split(/\W+/).filter(t => t.length > 2);
    const topK = options.topK || 10;
    const scored = [];
    
    const weakWords = new Set([
      'data', 'info', 'system', 'file', 'text', 'code', 'app', 'api',
      'the', 'and', 'for', 'with', 'from', 'that', 'this', 'have',
      'not', 'are', 'was', 'will', 'can', 'you', 'all', 'any'
    ]);
    
    const strongTokens = tokens.filter(t => !weakWords.has(t) || tokens.length === 1);
    const useTokens = strongTokens.length > 0 ? strongTokens : tokens;
    
    for (const memory of this.memories.values()) {
      if (memory.id.startsWith('__')) continue;
      
      const contentHaystack = `${memory.content} ${(memory.tags || []).join(' ')}`.toLowerCase();
      const idLower = memory.id.toLowerCase();
      let score = 0;
      let matchedTokens = 0;
      let tagMatches = 0;
      
      for (const token of useTokens) {
        const regex = new RegExp(`\\b${token}\\b`, 'g');
        const contentMatches = (contentHaystack.match(regex) || []).length;
        const idMatch = idLower.includes(token) && token.length >= 5 && !weakWords.has(token);
        
        if (contentMatches > 0 || idMatch) {
          matchedTokens++;
          score += contentMatches;
          if (idMatch) score += 1;
        }
        
        if ((memory.tags || []).some(t => t.toLowerCase() === token)) {
          score += 10;
          tagMatches++;
        } else if ((memory.tags || []).some(t => t.toLowerCase().includes(token))) {
          score += 5;
          tagMatches++;
        }
      }
      
      const hasStrongEvidence = matchedTokens >= 2 || tagMatches >= 1 || 
        (useTokens.length === 1 && score >= 5);
      
      if (!hasStrongEvidence) continue;
      
      score *= (1 + (memory.importance || 50) / 100);
      
      scored.push({ memory, score, matchedTokens, tagMatches });
    }
    
    return scored
      .sort((a, b) => b.score - a.score)
      .slice(0, topK)
      .map(({ memory, score }) => ({ memory, score: score.toFixed(2), method: 'keyword' }));
  }

  async getRelatedMemories(key, options = {}) {
    const memory = this.memories.get(key);
    if (!memory) return [];
    
    const topK = options.topK || 5;
    
    const concepts = this.knowledgeGraph.extractConcepts(memory.content);
    const relatedIds = this.knowledgeGraph.findMemoriesByConcepts(concepts, false);
    
    let vectorResults = [];
    if (memory.chunks?.length > 0) {
      const firstChunk = this.chunkStore.getMemoryChunks(key)[0];
      if (firstChunk?.embedding) {
        vectorResults = this.vectorStore.findSimilar(firstChunk.id, { topK });
      }
    }
    
    const combined = new Map();
    
    for (const id of relatedIds) {
      if (id !== key) {
        combined.set(id, (combined.get(id) || 0) + 0.5);
      }
    }
    
    for (const result of vectorResults) {
      const memId = result.metadata?.memoryId;
      if (memId && memId !== key) {
        combined.set(memId, (combined.get(memId) || 0) + result.score);
      }
    }
    
    return Array.from(combined.entries())
      .map(([id, score]) => ({ memory: this.memories.get(id), score }))
      .filter(r => r.memory)
      .sort((a, b) => b.score - a.score)
      .slice(0, topK);
  }

  async deleteMemory(key) {
    const exists = this.sqliteBackend.get(key) !== null || this.memories.has(key);
    
    if (!exists) {
      return { deleted: false, error: 'Memory not found' };
    }
    
    return this.transactionManager.run(async (tx) => {
      tx.addOperation('delete', { key }, async () => {});
      
      this.chunkStore.deleteMemoryChunks(key);
      this.vectorStore.deleteByMemoryId(key);
      this.memories.delete(key);
      this.sqliteBackend.delete(key);
      
      await this.eventBus.publish(MemoryEvents.MEMORY_DELETED, { memoryId: key });
      
      return { deleted: true, key };
    });
  }

  listMemories(options = {}) {
    let memories = Array.from(this.memories.values())
      .filter(m => !m.id.startsWith('__'));
    
    if (options.filter) {
      const filter = options.filter.toLowerCase();
      memories = memories.filter(m => 
        m.id.toLowerCase().includes(filter) ||
        m.tags?.some(t => t.toLowerCase().includes(filter))
      );
    }
    
    if (options.sortBy) {
      memories.sort((a, b) => {
        const aVal = a[options.sortBy] || 0;
        const bVal = b[options.sortBy] || 0;
        return options.sortOrder === 'asc' ? aVal - bVal : bVal - aVal;
      });
    }
    
    return memories;
  }

  async getTopicMemories(topic, options = {}) {
    const expanded = await this.expandTopic(topic);
    const memoryIds = this.knowledgeGraph.findMemoriesByConcepts(expanded, false);
    
    return memoryIds
      .map(id => this.memories.get(id))
      .filter(Boolean)
      .sort((a, b) => (b.importance || 0) - (a.importance || 0));
  }

  async expandTopic(topic) {
    const normalized = this.knowledgeGraph.normalizeConcept(topic);
    const related = this.knowledgeGraph.getRelatedConcepts(normalized, 2);
    return [topic, ...related.map(r => r.concept)];
  }

  getStats() {
    const memories = Array.from(this.memories.values()).filter(m => !m.id.startsWith('__'));
    const tagCount = {};
    
    memories.forEach(m => {
      (m.tags || []).forEach(t => {
        tagCount[t] = (tagCount[t] || 0) + 1;
      });
    });
    
    const topTags = Object.entries(tagCount)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 15);
    
    const sqliteStats = this.sqliteBackend.getStats();
    
    return {
      totalMemories: memories.length,
      totalChunks: this.chunkStore.getStats().totalChunks,
      totalEmbeddings: this.vectorStore.getStats().totalVectors,
      totalConcepts: this.knowledgeGraph.getStats().concepts,
      avgImportance: memories.length > 0 
        ? (memories.reduce((sum, m) => sum + (m.importance || 50), 0) / memories.length).toFixed(1)
        : 0,
      intelligenceEnabled: !!this.intelligenceProvider?.isAvailable?.(),
      topTags,
      storage: {
        primary: 'sqlite',
        sqlite: sqliteStats
      }
    };
  }

  async createSnapshot() {
    const snapshotDir = path.join(this.dataDir, 'snapshots');
    if (!fs.existsSync(snapshotDir)) {
      fs.mkdirSync(snapshotDir, { recursive: true });
    }
    
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    const snapshotPath = path.join(snapshotDir, `snapshot-${timestamp}.json`);
    
    const data = {
      exportedAt: new Date().toISOString(),
      memories: Array.from(this.memories.values()),
      vectors: this.vectorStore.export(),
      graph: this.knowledgeGraph.export()
    };
    
    fs.writeFileSync(snapshotPath, JSON.stringify(data, null, 2));
    return snapshotPath;
  }

  export() {
    return {
      memories: Array.from(this.memories.entries()),
      chunks: this.chunkStore.export(),
      vectors: this.vectorStore.export(),
      graph: this.knowledgeGraph.export()
    };
  }

  async import(data) {
    this.memories = new Map(data.memories);
    this.chunkStore.import(data.chunks);
    this.vectorStore.import(data.vectors);
    for (const memory of this.memories.values()) {
      this.sqliteBackend.insert(memory);
      await this.knowledgeGraph.buildFromMemory(memory.id, memory.content, memory.tags);
    }
  }
}
