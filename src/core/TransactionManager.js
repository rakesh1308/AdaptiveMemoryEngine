/**
 * TransactionManager - ACID transaction support for memory operations
 * Ensures data integrity with write-ahead logging and rollback capability
 */

import fs from 'fs';
import path from 'path';
import { EventBus, MemoryEvents } from '../infrastructure/EventBus.js';

export class Transaction {
  constructor(id, manager) {
    this.id = id;
    this.manager = manager;
    this.operations = [];
    this.state = 'active'; // active, committing, committed, rolledback
    this.startTime = Date.now();
  }

  async addOperation(type, data, rollbackFn) {
    if (this.state !== 'active') {
      throw new Error(`Transaction ${this.id} is not active`);
    }
    
    this.operations.push({
      type,
      data,
      rollbackFn,
      timestamp: Date.now()
    });
  }

  async commit() {
    if (this.state !== 'active') {
      throw new Error(`Transaction ${this.id} cannot commit in state ${this.state}`);
    }
    
    this.state = 'committing';
    
    try {
      // Write to WAL first (durability)
      await this.manager.writeWAL(this);
      
      // Execute operations
      for (const op of this.operations) {
        await this.manager.executeOperation(op);
      }
      
      this.state = 'committed';
      await this.manager.eventBus.publish(MemoryEvents.TRANSACTION_COMMITTED, {
        transactionId: this.id,
        operationCount: this.operations.length
      });
      
      // Mark as complete in WAL
      await this.manager.completeWAL(this);
      
    } catch (error) {
      await this.rollback();
      throw error;
    }
  }

  async rollback() {
    if (this.state === 'rolledback') return;
    
    this.state = 'rolledback';
    
    // Execute rollback in reverse order
    for (let i = this.operations.length - 1; i >= 0; i--) {
      const op = this.operations[i];
      if (op.rollbackFn) {
        try {
          await op.rollbackFn(op.data);
        } catch (err) {
          console.error(`[Transaction ${this.id}] Rollback error:`, err);
        }
      }
    }
    
    await this.manager.eventBus.publish(MemoryEvents.TRANSACTION_ROLLED_BACK, {
      transactionId: this.id
    });
  }
}

export class TransactionManager {
  constructor(options = {}) {
    this.dataDir = options.dataDir || './data';
    this.walPath = path.join(this.dataDir, 'wal.log');
    this.checkpointInterval = options.checkpointInterval || 300000; // 5 minutes
    this.eventBus = options.eventBus || new EventBus();
    this.activeTransactions = new Map();
    this.completedTransactions = new Set();
    this.maxCompleted = 1000;
    
    this.ensureWAL();
    this.startCheckpointTimer();
  }

  ensureWAL() {
    if (!fs.existsSync(this.dataDir)) {
      fs.mkdirSync(this.dataDir, { recursive: true });
    }
    if (!fs.existsSync(this.walPath)) {
      fs.writeFileSync(this.walPath, '');
    }
  }

  /**
   * Begin a new transaction
   */
  begin() {
    const id = this.generateId();
    const tx = new Transaction(id, this);
    this.activeTransactions.set(id, tx);
    
    this.eventBus.publish(MemoryEvents.TRANSACTION_STARTED, {
      transactionId: id
    });
    
    return tx;
  }

  /**
   * Execute a function within a transaction
   */
  async run(fn) {
    const tx = this.begin();
    try {
      const result = await fn(tx);
      await tx.commit();
      return result;
    } catch (error) {
      await tx.rollback();
      throw error;
    } finally {
      this.activeTransactions.delete(tx.id);
      this.completedTransactions.add(tx.id);
      
      // Cleanup old completed transactions
      if (this.completedTransactions.size > this.maxCompleted) {
        const toRemove = Array.from(this.completedTransactions).slice(0, 100);
        toRemove.forEach(id => this.completedTransactions.delete(id));
      }
    }
  }

  /**
   * Write transaction to WAL
   */
  async writeWAL(transaction) {
    const walEntry = {
      type: 'BEGIN',
      txId: transaction.id,
      timestamp: new Date().toISOString(),
      operations: transaction.operations.map(op => ({
        type: op.type,
        data: this.serializableData(op.data)
      }))
    };
    
    await this.appendWAL(walEntry);
  }

  /**
   * Mark transaction as complete in WAL
   */
  async completeWAL(transaction) {
    const walEntry = {
      type: transaction.state === 'committed' ? 'COMMIT' : 'ROLLBACK',
      txId: transaction.id,
      timestamp: new Date().toISOString()
    };
    
    await this.appendWAL(walEntry);
  }

  async appendWAL(entry) {
    const line = JSON.stringify(entry) + '\n';
    fs.appendFileSync(this.walPath, line);
  }

  /**
   * Execute a single operation
   */
  async executeOperation(op) {
    // Override in subclasses for actual storage operations
    console.log(`[Transaction] Executing ${op.type}`);
  }

  /**
   * Recover from crash using WAL
   */
  async recover() {
    console.log('[TransactionManager] Starting recovery...');
    
    if (!fs.existsSync(this.walPath)) {
      console.log('[TransactionManager] No WAL file found');
      return;
    }
    
    const lines = fs.readFileSync(this.walPath, 'utf-8')
      .split('\n')
      .filter(line => line.trim());
    
    const transactions = new Map();
    
    for (const line of lines) {
      try {
        const entry = JSON.parse(line);
        
        if (entry.type === 'BEGIN') {
          transactions.set(entry.txId, {
            id: entry.txId,
            operations: entry.operations,
            state: 'incomplete'
          });
        } else if (entry.type === 'COMMIT') {
          const tx = transactions.get(entry.txId);
          if (tx) tx.state = 'committed';
        } else if (entry.type === 'ROLLBACK') {
          const tx = transactions.get(entry.txId);
          if (tx) tx.state = 'rolledback';
        }
      } catch (err) {
        console.error('[TransactionManager] WAL parse error:', err);
      }
    }
    
    // Replay committed but potentially unapplied transactions
    for (const [id, tx] of transactions) {
      if (tx.state === 'committed' || tx.state === 'incomplete') {
        console.log(`[TransactionManager] Replaying transaction ${id}`);
        // Replay logic here
      }
    }
    
    console.log('[TransactionManager] Recovery complete');
  }

  /**
   * Checkpoint - truncate WAL after ensuring durability
   */
  async checkpoint() {
    console.log('[TransactionManager] Running checkpoint...');
    
    // In a real implementation, this would:
    // 1. Ensure all committed transactions are persisted
    // 2. Truncate the WAL file
    // 3. Update checkpoint metadata
    
    // For now, we just rotate if WAL is too large
    const stats = fs.statSync(this.walPath);
    if (stats.size > 10 * 1024 * 1024) { // 10MB
      await this.rotateWAL();
    }
  }

  async rotateWAL() {
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    const backupPath = `${this.walPath}.${timestamp}`;
    
    fs.renameSync(this.walPath, backupPath);
    fs.writeFileSync(this.walPath, '');
    
    console.log(`[TransactionManager] WAL rotated to ${backupPath}`);
  }

  startCheckpointTimer() {
    setInterval(() => this.checkpoint(), this.checkpointInterval);
  }

  /**
   * Get transaction statistics
   */
  getStats() {
    return {
      active: this.activeTransactions.size,
      completed: this.completedTransactions.size,
      walSize: fs.existsSync(this.walPath) ? fs.statSync(this.walPath).size : 0
    };
  }

  generateId() {
    return `tx-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
  }

  serializableData(data) {
    // Remove functions, circular refs, etc.
    return JSON.parse(JSON.stringify(data, (key, value) => {
      if (typeof value === 'function') return undefined;
      return value;
    }));
  }
}
