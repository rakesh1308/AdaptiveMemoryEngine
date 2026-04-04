/**
 * AdaptiveMemoryEngine
 * Main exports for the memory system
 */

// Core
export { MemoryEngine } from './core/MemoryEngine.js';
export { TransactionManager, Transaction } from './core/TransactionManager.js';
export { ChunkStore, ChunkingStrategies } from './core/ChunkStore.js';

// Intelligence
export { KnowledgeGraph } from './intelligence/KnowledgeGraph.js';

// Lifecycle
export { 
  MemoryLifecycle,
  ImportanceScorer,
  DecayEngine,
  ConsolidationEngine,
  ArchiveManager
} from './lifecycle/MemoryLifecycle.js';

// Storage
export { VectorStore } from './storage/VectorStore.js';
export { SQLiteBackend } from './storage/backends/SQLiteBackend.js';

// Infrastructure
export { EventBus, MemoryEvents } from './infrastructure/EventBus.js';
export { HealthMonitor, HealthChecks } from './infrastructure/HealthMonitor.js';

// Utils
export { OpenAIProvider } from './utils/OpenAIProvider.js';
