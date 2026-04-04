/**
 * StorageBackend Interface
 * All storage backends must implement this interface
 * 
 * Usage:
 *   class MyBackend extends StorageBackend { ... }
 */

export class StorageBackend {
  constructor(options = {}) {
    this.dataDir = options.dataDir || './data';
    this.name = this.constructor.name;
  }

  /**
   * Initialize the backend
   * @returns {Promise<boolean>} - True if successfully initialized
   */
  async initialize() {
    throw new Error('initialize() must be implemented');
  }

  /**
   * Check if backend is available/ready
   * @returns {boolean}
   */
  isAvailable() {
    throw new Error('isAvailable() must be implemented');
  }

  /**
   * Store a memory
   * @param {Object} memory - Memory object with id, content, tags, etc.
   * @returns {Promise<Object>} - Stored memory
   */
  async store(memory) {
    throw new Error('store() must be implemented');
  }

  /**
   * Retrieve a memory by ID
   * @param {string} id - Memory ID
   * @returns {Promise<Object|null>} - Memory or null if not found
   */
  async retrieve(id) {
    throw new Error('retrieve() must be implemented');
  }

  /**
   * Update a memory
   * @param {string} id - Memory ID
   * @param {Object} updates - Fields to update
   * @returns {Promise<Object>} - Updated memory
   */
  async update(id, updates) {
    throw new Error('update() must be implemented');
  }

  /**
   * Delete a memory
   * @param {string} id - Memory ID
   * @returns {Promise<boolean>} - True if deleted
   */
  async delete(id) {
    throw new Error('delete() must be implemented');
  }

  /**
   * List all memories
   * @param {Object} options - { limit, offset, filter }
   * @returns {Promise<Array>} - Array of memories
   */
  async list(options = {}) {
    throw new Error('list() must be implemented');
  }

  /**
   * Search memories by keyword
   * @param {string} query - Search query
   * @param {Object} options - { limit, filters }
   * @returns {Promise<Array>} - Matching memories
   */
  async search(query, options = {}) {
    throw new Error('search() must be implemented');
  }

  /**
   * Store embedding for a chunk
   * @param {string} chunkId - Chunk ID
   * @param {Array<number>} embedding - Vector embedding
   * @returns {Promise<boolean>}
   */
  async storeEmbedding(chunkId, embedding) {
    throw new Error('storeEmbedding() must be implemented');
  }

  /**
   * Retrieve embedding for a chunk
   * @param {string} chunkId - Chunk ID
   * @returns {Promise<Array<number>|null>} - Embedding or null
   */
  async retrieveEmbedding(chunkId) {
    throw new Error('retrieveEmbedding() must be implemented');
  }

  /**
   * Get all embeddings
   * @returns {Promise<Map<string, Array<number>>>} - Map of chunkId to embedding
   */
  async getAllEmbeddings() {
    throw new Error('getAllEmbeddings() must be implemented');
  }

  /**
   * Create a snapshot/backup
   * @param {string} snapshotPath - Path for snapshot
   * @returns {Promise<string>} - Snapshot path
   */
  async createSnapshot(snapshotPath) {
    throw new Error('createSnapshot() must be implemented');
  }

  /**
   * Close the backend (cleanup)
   * @returns {Promise<void>}
   */
  async close() {
    // Optional: override if needed
  }

  /**
   * Get backend statistics
   * @returns {Promise<Object>} - Stats object
   */
  async getStats() {
    throw new Error('getStats() must be implemented');
  }
}
