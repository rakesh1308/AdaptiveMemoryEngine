/**
 * SearchStrategy Interface
 * Pluggable search strategies (keyword, semantic, hybrid, etc.)
 * 
 * Usage:
 *   class SemanticSearch extends SearchStrategy { ... }
 *   class HybridSearch extends SearchStrategy { ... }
 */

export class SearchStrategy {
  constructor(options = {}) {
    this.name = options.name || this.constructor.name;
    this.weight = options.weight || 1.0;
  }

  /**
   * Check if strategy is available
   * @returns {boolean}
   */
  isAvailable() {
    return true;
  }

  /**
   * Search memories
   * @param {string} query - Search query
   * @param {Map<string, Object>} memories - All memories
   * @param {Object} context - Additional context (vectorStore, knowledgeGraph, etc.)
   * @param {Object} options - Search options { topK, filters }
   * @returns {Promise<Array<{memory: Object, score: number}>>} - Ranked results
   */
  async search(query, memories, context, options = {}) {
    throw new Error('search() must be implemented');
  }

  /**
   * Get strategy metadata
   * @returns {Object} - { name, description, requiresEmbedding, requiresGraph }
   */
  getMetadata() {
    return {
      name: this.name,
      description: 'Search strategy',
      requiresEmbedding: false,
      requiresGraph: false
    };
  }
}

/**
 * KeywordSearch - Simple keyword matching
 */
export class KeywordSearchStrategy extends SearchStrategy {
  async search(query, memories, context, options = {}) {
    const terms = query.toLowerCase().split(/\s+/);
    const results = [];
    const { topK = 10 } = options;

    for (const [id, memory] of memories) {
      const text = (memory.content + ' ' + (memory.tags?.join(' ') || '')).toLowerCase();
      let score = 0;
      
      for (const term of terms) {
        if (term.length < 3) continue;
        const matches = (text.match(new RegExp(term, 'g')) || []).length;
        score += matches * (term.length / 10);
      }
      
      if (score > 0) {
        results.push({ memory, score: Math.min(score / terms.length, 1.0) });
      }
    }

    return results
      .sort((a, b) => b.score - a.score)
      .slice(0, topK);
  }

  getMetadata() {
    return {
      name: 'keyword',
      description: 'Simple keyword matching',
      requiresEmbedding: false,
      requiresGraph: false
    };
  }
}
