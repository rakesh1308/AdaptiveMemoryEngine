/**
 * EmbeddingProvider Interface
 * All AI/embedding providers must implement this interface
 * 
 * Usage:
 *   class OllamaProvider extends EmbeddingProvider { ... }
 *   class OpenAIProvider extends EmbeddingProvider { ... }
 */

export class EmbeddingProvider {
  constructor(options = {}) {
    this.name = options.name || this.constructor.name;
    this.dimensions = options.dimensions || 1536;
  }

  /**
   * Check if provider is available (has credentials, reachable, etc.)
   * @returns {boolean}
   */
  isAvailable() {
    throw new Error('isAvailable() must be implemented');
  }

  /**
   * Get embedding for single text
   * @param {string} text - Text to embed
   * @returns {Promise<Array<number>|null>} - Embedding vector or null
   */
  async embed(text) {
    throw new Error('embed() must be implemented');
  }

  /**
   * Get embeddings for multiple texts (batch)
   * @param {Array<string>} texts - Array of texts
   * @returns {Promise<Array<Array<number>|null>>} - Array of embeddings
   */
  async embedBatch(texts) {
    // Default: sequential embed
    const results = [];
    for (const text of texts) {
      results.push(await this.embed(text));
    }
    return results;
  }

  /**
   * Calculate similarity between two embeddings
   * @param {Array<number>} a - First embedding
   * @param {Array<number>} b - Second embedding
   * @returns {number} - Similarity score (0-1)
   */
  similarity(a, b) {
    // Default: cosine similarity
    if (!a || !b || a.length !== b.length) return 0;
    
    let dot = 0;
    let normA = 0;
    let normB = 0;
    
    for (let i = 0; i < a.length; i++) {
      dot += a[i] * b[i];
      normA += a[i] * a[i];
      normB += b[i] * b[i];
    }
    
    return dot / (Math.sqrt(normA) * Math.sqrt(normB));
  }
}

/**
 * IntelligentProvider Interface (extends EmbeddingProvider)
 * For providers that also support AI features (tagging, synthesis)
 */
export class IntelligentProvider extends EmbeddingProvider {
  constructor(options = {}) {
    super(options);
  }

  /**
   * Auto-generate tags for content
   * @param {string} key - Memory key/title
   * @param {string} content - Memory content
   * @returns {Promise<Array<string>>} - Array of tags
   */
  async autoTag(key, content) {
    // Optional: return empty array if not supported
    return [];
  }

  /**
   * Synthesize content for a task
   * @param {string} content - Source content
   * @param {string} task - Task description
   * @param {string} style - Output style
   * @returns {Promise<string>} - Synthesized content
   */
  async synthesize(content, task, style = '') {
    // Optional: return raw content if not supported
    return content;
  }

  /**
   * Expand query into related search terms
   * @param {string} query - Original query
   * @returns {Promise<Array<string>>} - Expanded terms
   */
  async expandQuery(query) {
    // Optional: return original if not supported
    return [query];
  }
}
