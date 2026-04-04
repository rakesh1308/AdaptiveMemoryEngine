/**
 * EventBus - Central pub/sub system for the memory system
 * Enables loose coupling between components and supports plugin extensions
 */

export class EventBus {
  constructor() {
    this.subscribers = new Map();
    this.middleware = [];
    this.history = []; // For debugging/replay
    this.maxHistory = 1000;
  }

  /**
   * Subscribe to an event type
   * @param {string} eventType - Event type or wildcard pattern
   * @param {Function} handler - Event handler
   * @returns {Function} Unsubscribe function
   */
  subscribe(eventType, handler) {
    if (!this.subscribers.has(eventType)) {
      this.subscribers.set(eventType, new Set());
    }
    this.subscribers.get(eventType).add(handler);
    
    return () => this.unsubscribe(eventType, handler);
  }

  /**
   * Subscribe once to an event
   * @param {string} eventType - Event type
   * @param {Function} handler - Event handler
   */
  once(eventType, handler) {
    const wrapped = (payload) => {
      this.unsubscribe(eventType, wrapped);
      handler(payload);
    };
    this.subscribe(eventType, wrapped);
  }

  /**
   * Unsubscribe from an event
   */
  unsubscribe(eventType, handler) {
    const handlers = this.subscribers.get(eventType);
    if (handlers) {
      handlers.delete(handler);
      if (handlers.size === 0) {
        this.subscribers.delete(eventType);
      }
    }
  }

  /**
   * Add middleware to process events
   */
  use(middleware) {
    this.middleware.push(middleware);
  }

  /**
   * Publish an event
   */
  async publish(eventType, payload = {}) {
    const event = {
      type: eventType,
      payload,
      timestamp: new Date().toISOString(),
      id: this.generateId()
    };

    // Run through middleware
    for (const mw of this.middleware) {
      try {
        await mw(event);
      } catch (err) {
        console.error(`[EventBus] Middleware error: ${err.message}`);
      }
    }

    // Store in history
    this.history.push(event);
    if (this.history.length > this.maxHistory) {
      this.history.shift();
    }

    // Notify subscribers
    const handlers = this.subscribers.get(eventType);
    if (handlers) {
      for (const handler of handlers) {
        try {
          await handler(event.payload, event);
        } catch (err) {
          console.error(`[EventBus] Handler error for ${eventType}: ${err.message}`);
        }
      }
    }

    // Notify wildcard subscribers
    const wildcards = this.subscribers.get('*');
    if (wildcards) {
      for (const handler of wildcards) {
        try {
          await handler(event);
        } catch (err) {
          console.error(`[EventBus] Wildcard handler error: ${err.message}`);
        }
      }
    }

    return event;
  }

  /**
   * Get event history
   */
  getHistory(eventType = null, limit = 100) {
    let events = this.history;
    if (eventType) {
      events = events.filter(e => e.type === eventType);
    }
    return events.slice(-limit);
  }

  /**
   * Replay events from history
   */
  async replay(fromTimestamp = null) {
    let events = this.history;
    if (fromTimestamp) {
      events = events.filter(e => e.timestamp >= fromTimestamp);
    }
    
    for (const event of events) {
      await this.publish(event.type, event.payload);
    }
  }

  /**
   * Clear all subscribers and history
   */
  clear() {
    this.subscribers.clear();
    this.middleware = [];
    this.history = [];
  }

  generateId() {
    return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
  }
}

// Predefined event types for the memory system
export const MemoryEvents = {
  // Memory lifecycle
  MEMORY_CREATED: 'memory:created',
  MEMORY_UPDATED: 'memory:updated',
  MEMORY_DELETED: 'memory:deleted',
  MEMORY_ACCESSED: 'memory:accessed',
  MEMORY_ARCHIVED: 'memory:archived',
  MEMORY_RESTORED: 'memory:restored',
  
  // Chunk operations
  CHUNK_CREATED: 'chunk:created',
  CHUNK_EMBEDDED: 'chunk:embedded',
  
  // Intelligence
  CONCEPT_EXTRACTED: 'concept:extracted',
  RELATIONSHIP_ADDED: 'relationship:added',
  GRAPH_UPDATED: 'graph:updated',
  
  // Lifecycle
  IMPORTANCE_UPDATED: 'importance:updated',
  DECAY_APPLIED: 'decay:applied',
  CONSOLIDATION_RUN: 'consolidation:run',
  
  // System
  TRANSACTION_STARTED: 'transaction:started',
  TRANSACTION_COMMITTED: 'transaction:committed',
  TRANSACTION_ROLLED_BACK: 'transaction:rolledback',
  BACKUP_CREATED: 'backup:created',
  BACKUP_RESTORED: 'backup:restored',
  ERROR_OCCURRED: 'error:occurred'
};
