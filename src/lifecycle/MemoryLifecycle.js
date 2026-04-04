/**
 * MemoryLifecycle - Manages the complete lifecycle of memories
 * Handles importance scoring, decay, consolidation, and archiving
 */

import { EventBus, MemoryEvents } from '../infrastructure/EventBus.js';

export class ImportanceScorer {
  constructor(options = {}) {
    this.weights = {
      accessFrequency: options.accessWeight || 0.25,
      recency: options.recencyWeight || 0.20,
      userRating: options.ratingWeight || 0.20,
      graphCentrality: options.centralityWeight || 0.15,
      contentQuality: options.qualityWeight || 0.10,
      referenceCount: options.referenceWeight || 0.10
    };
    this.decayRate = options.decayRate || 0.05;
  }

  /**
   * Calculate importance score for a memory
   */
  calculate(memory, graphNode = null) {
    const now = Date.now();
    const age = now - new Date(memory.createdAt).getTime();
    const lastAccess = memory.lastAccessed 
      ? now - new Date(memory.lastAccessed).getTime()
      : age;
    
    // Access frequency (normalized log scale)
    const accessScore = Math.min(1, Math.log10((memory.accessCount || 0) + 1) / 3);
    
    // Recency (exponential decay)
    const recencyScore = Math.exp(-lastAccess / (30 * 24 * 60 * 60 * 1000)); // 30 days
    
    // User rating (explicit or implicit)
    const ratingScore = (memory.userRating || 3) / 5;
    
    // Graph centrality (from knowledge graph)
    const centralityScore = graphNode?.centrality 
      ? Math.min(1, graphNode.centrality / 10)
      : 0;
    
    // Content quality heuristics
    const qualityScore = this.assessContentQuality(memory.content);
    
    // Reference count
    const referenceScore = Math.min(1, (memory.references?.length || 0) / 5);
    
    // Weighted sum
    const importance = 
      this.weights.accessFrequency * accessScore +
      this.weights.recency * recencyScore +
      this.weights.userRating * ratingScore +
      this.weights.graphCentrality * centralityScore +
      this.weights.contentQuality * qualityScore +
      this.weights.referenceCount * referenceScore;
    
    return Math.round(importance * 100);
  }

  /**
   * Heuristic content quality assessment
   */
  assessContentQuality(content) {
    if (!content) return 0;
    
    let score = 0.5; // Base score
    
    // Length factor (prefer substantial content but not excessive)
    const length = content.length;
    if (length > 500 && length < 10000) score += 0.2;
    else if (length >= 10000) score += 0.1;
    
    // Structure indicators
    if (content.includes('#')) score += 0.1; // Has headings
    if (content.includes('```')) score += 0.1; // Has code blocks
    if (/\[.*?\]\(.*?\)/.test(content)) score += 0.1; // Has links
    
    // Content richness
    const uniqueWords = new Set(content.toLowerCase().split(/\s+/)).size;
    const richness = uniqueWords / (length / 5); // words per 5 chars
    if (richness > 0.5) score += 0.1;
    
    return Math.min(1, score);
  }
}

export class DecayEngine {
  constructor(options = {}) {
    this.baseRate = options.decayRate || 0.05;
    this.halfLife = options.halfLife || 30; // days
    this.minStrength = options.minStrength || 0.1;
    this.eventBus = options.eventBus || new EventBus();
  }

  /**
   * Calculate current memory strength using forgetting curve
   * Based on Ebbinghaus forgetting curve: R = e^(-t/S)
   * where R = retention, t = time, S = stability
   */
  calculateStrength(memory, now = new Date()) {
    const lastAccess = memory.lastAccessed 
      ? new Date(memory.lastAccessed)
      : new Date(memory.createdAt);
    
    const daysSinceAccess = (now - lastAccess) / (1000 * 60 * 60 * 24);
    
    // Importance increases stability
    const stability = this.halfLife * (1 + (memory.importance || 50) / 50);
    
    // Forgetting curve
    const retention = Math.exp(-daysSinceAccess / stability);
    
    // Apply minimum threshold
    return Math.max(this.minStrength, retention);
  }

  /**
   * Determine if memory should be reviewed (spaced repetition)
   */
  shouldReview(memory, now = new Date()) {
    const strength = this.calculateStrength(memory, now);
    
    // Review when strength drops below threshold
    if (strength < 0.3) return { needed: true, priority: 'high' };
    if (strength < 0.5) return { needed: true, priority: 'medium' };
    if (strength < 0.7) return { needed: true, priority: 'low' };
    
    return { needed: false };
  }

  /**
   * Schedule next review based on performance
   */
  scheduleReview(memory, performance = 'good') {
    const intervals = {
      poor: 1,      // 1 day
      fair: 3,      // 3 days
      good: 7,      // 1 week
      excellent: 14 // 2 weeks
    };
    
    const days = intervals[performance] || intervals.good;
    const nextReview = new Date();
    nextReview.setDate(nextReview.getDate() + days);
    
    return nextReview;
  }

  /**
   * Apply decay to all memories
   */
  async applyDecay(memories, now = new Date()) {
    const results = [];
    
    for (const memory of memories) {
      const strength = this.calculateStrength(memory, now);
      const needsReview = this.shouldReview(memory, now);
      
      results.push({
        memoryId: memory.id,
        strength,
        needsReview: needsReview.needed,
        priority: needsReview.priority
      });
    }
    
    await this.eventBus.publish(MemoryEvents.DECAY_APPLIED, {
      count: results.length,
      needsReview: results.filter(r => r.needsReview).length
    });
    
    return results;
  }
}

export class ConsolidationEngine {
  constructor(options = {}) {
    this.similarityThreshold = options.similarityThreshold || 0.85;
    this.eventBus = options.eventBus || new EventBus();
  }

  /**
   * Find potentially duplicate memories
   */
  async findDuplicates(memories) {
    const groups = [];
    const processed = new Set();
    
    for (let i = 0; i < memories.length; i++) {
      if (processed.has(i)) continue;
      
      const group = [memories[i]];
      processed.add(i);
      
      for (let j = i + 1; j < memories.length; j++) {
        if (processed.has(j)) continue;
        
        const similarity = this.calculateSimilarity(memories[i], memories[j]);
        if (similarity >= this.similarityThreshold) {
          group.push(memories[j]);
          processed.add(j);
        }
      }
      
      if (group.length > 1) {
        groups.push(group);
      }
    }
    
    return groups;
  }

  /**
   * Calculate similarity between two memories
   */
  calculateSimilarity(a, b) {
    // Simple Jaccard similarity on words
    const wordsA = new Set(a.content.toLowerCase().split(/\s+/));
    const wordsB = new Set(b.content.toLowerCase().split(/\s+/));
    
    const intersection = new Set([...wordsA].filter(x => wordsB.has(x)));
    const union = new Set([...wordsA, ...wordsB]);
    
    const jaccard = intersection.size / union.size;
    
    // Tag overlap bonus
    const tagsA = new Set(a.tags || []);
    const tagsB = new Set(b.tags || []);
    const tagOverlap = [...tagsA].filter(t => tagsB.has(t)).length;
    const tagBonus = Math.min(0.2, tagOverlap * 0.1);
    
    return Math.min(1, jaccard + tagBonus);
  }

  /**
   * Merge duplicate memories into one
   */
  async mergeMemories(group) {
    if (group.length === 0) return null;
    if (group.length === 1) return group[0];
    
    // Select primary (most recent or most accessed)
    const primary = group.sort((a, b) => {
      const aScore = (a.accessCount || 0) + (a.importance || 0);
      const bScore = (b.accessCount || 0) + (b.importance || 0);
      return bScore - aScore;
    })[0];
    
    // Combine content intelligently
    const combinedContent = this.combineContent(group);
    
    // Merge tags
    const allTags = new Set();
    group.forEach(m => (m.tags || []).forEach(t => allTags.add(t)));
    
    // Merge metadata
    const totalAccesses = group.reduce((sum, m) => sum + (m.accessCount || 0), 0);
    const maxImportance = Math.max(...group.map(m => m.importance || 0));
    
    const merged = {
      ...primary,
      content: combinedContent,
      tags: Array.from(allTags),
      accessCount: totalAccesses,
      importance: maxImportance,
      mergedFrom: group.map(m => m.id),
      updatedAt: new Date().toISOString()
    };
    
    return merged;
  }

  /**
   * Combine content from multiple memories intelligently
   */
  combineContent(memories) {
    // Simple approach: take the longest content
    // In production, use AI to synthesize
    return memories
      .sort((a, b) => b.content.length - a.content.length)[0]
      .content;
  }

  /**
   * Synthesize a summary from multiple memories on a topic
   */
  async synthesizeTopic(memories, topic) {
    const sorted = memories.sort((a, b) => b.importance - a.importance);
    
    return {
      topic,
      summary: `Synthesis of ${memories.length} memories on ${topic}`,
      sources: sorted.map(m => m.id),
      keyPoints: sorted.slice(0, 5).map(m => ({
        source: m.id,
        content: m.content.substring(0, 200)
      }))
    };
  }
}

export class ArchiveManager {
  constructor(options = {}) {
    this.archiveThreshold = options.archiveThreshold || 0.1; // strength threshold
    this.archiveAfterDays = options.archiveAfterDays || 90;
    this.archiveDir = options.archiveDir || './data/archives';
    this.archived = new Map();
    this.eventBus = options.eventBus || new EventBus();
  }

  /**
   * Check if memory should be archived
   */
  shouldArchive(memory, decayResult) {
    // Don't archive important memories
    if ((memory.importance || 0) > 80) return false;
    
    // Archive if strength is very low
    if (decayResult?.strength < this.archiveThreshold) return true;
    
    // Archive if very old and never accessed
    const age = Date.now() - new Date(memory.createdAt).getTime();
    const daysOld = age / (1000 * 60 * 60 * 24);
    
    if (daysOld > this.archiveAfterDays && (memory.accessCount || 0) < 3) {
      return true;
    }
    
    return false;
  }

  /**
   * Archive a memory
   */
  async archive(memory) {
    const archivedMemory = {
      ...memory,
      archivedAt: new Date().toISOString(),
      originalId: memory.id
    };
    
    this.archived.set(memory.id, archivedMemory);
    
    await this.eventBus.publish(MemoryEvents.MEMORY_ARCHIVED, {
      memoryId: memory.id,
      archivedAt: archivedMemory.archivedAt
    });
    
    return archivedMemory;
  }

  /**
   * Restore an archived memory
   */
  async restore(memoryId) {
    const archived = this.archived.get(memoryId);
    if (!archived) return null;
    
    const restored = {
      ...archived,
      restoredAt: new Date().toISOString(),
      strength: 0.5 // Reset strength
    };
    
    delete restored.archivedAt;
    this.archived.delete(memoryId);
    
    await this.eventBus.publish(MemoryEvents.MEMORY_RESTORED, {
      memoryId,
      restoredAt: restored.restoredAt
    });
    
    return restored;
  }

  /**
   * Search archived memories
   */
  searchArchives(query) {
    const results = [];
    const q = query.toLowerCase();
    
    for (const memory of this.archived.values()) {
      if (memory.content.toLowerCase().includes(q) ||
          memory.id.toLowerCase().includes(q) ||
          memory.tags?.some(t => t.toLowerCase().includes(q))) {
        results.push(memory);
      }
    }
    
    return results;
  }

  /**
   * Get archive statistics
   */
  getStats() {
    return {
      archivedCount: this.archived.size,
      totalSize: Array.from(this.archived.values())
        .reduce((sum, m) => sum + (m.content?.length || 0), 0)
    };
  }
}

export class MemoryLifecycle {
  constructor(options = {}) {
    this.importanceScorer = new ImportanceScorer(options.importance);
    this.decayEngine = new DecayEngine(options.decay);
    this.consolidationEngine = new ConsolidationEngine(options.consolidation);
    this.archiveManager = new ArchiveManager(options.archive);
    this.eventBus = options.eventBus || new EventBus();
    
    // Configuration
    this.consolidationInterval = options.consolidationInterval || 24 * 60 * 60 * 1000; // 24 hours
    this.decayInterval = options.decayInterval || 60 * 60 * 1000; // 1 hour
    
    this.startTimers();
  }

  /**
   * Update memory lifecycle state
   */
  async updateMemory(memory, graphNode = null) {
    // Recalculate importance
    memory.importance = this.importanceScorer.calculate(memory, graphNode);
    
    // Calculate current strength
    memory.strength = this.decayEngine.calculateStrength(memory);
    
    // Check if should be archived
    const decayResult = this.decayEngine.shouldReview(memory);
    if (this.archiveManager.shouldArchive(memory, { strength: memory.strength })) {
      await this.archiveManager.archive(memory);
      return { archived: true };
    }
    
    return {
      importance: memory.importance,
      strength: memory.strength,
      needsReview: decayResult.needed,
      priority: decayResult.priority
    };
  }

  /**
   * Record memory access
   */
  async recordAccess(memory, context = {}) {
    memory.accessCount = (memory.accessCount || 0) + 1;
    memory.lastAccessed = new Date().toISOString();
    
    // Boost strength on access
    memory.strength = Math.min(1, (memory.strength || 0.5) + 0.1);
    
    await this.eventBus.publish(MemoryEvents.MEMORY_ACCESSED, {
      memoryId: memory.id,
      context,
      accessCount: memory.accessCount
    });
  }

  /**
   * Run consolidation process
   */
  async runConsolidation(memories) {
    console.log('[MemoryLifecycle] Running consolidation...');
    
    // Find and merge duplicates
    const duplicates = await this.consolidationEngine.findDuplicates(memories);
    const merged = [];
    
    for (const group of duplicates) {
      const result = await this.consolidationEngine.mergeMemories(group);
      if (result) {
        merged.push(result);
      }
    }
    
    await this.eventBus.publish(MemoryEvents.CONSOLIDATION_RUN, {
      duplicatesFound: duplicates.length,
      merged: merged.length
    });
    
    return { duplicates: duplicates.length, merged };
  }

  startTimers() {
    // Run decay check periodically
    setInterval(() => {
      console.log('[MemoryLifecycle] Running decay check...');
    }, this.decayInterval);
    
    // Run consolidation periodically
    setInterval(() => {
      // Would need access to memory store
    }, this.consolidationInterval);
  }
}
