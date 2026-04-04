/**
 * SQLiteBackend - Primary storage for memories
 * Uses Node.js built-in node:sqlite (Node 22+)
 */

import fs from 'fs';
import path from 'path';
import { DatabaseSync } from 'node:sqlite';

export class SQLiteBackend {
  constructor(options = {}) {
    this.dataDir = options.dataDir || './data';
    this.dbPath = options.dbPath || path.join(this.dataDir, 'memories.db');
    this.db = null;
    this.isAvailable = false;
  }

  async initialize() {
    try {
      if (!fs.existsSync(this.dataDir)) {
        fs.mkdirSync(this.dataDir, { recursive: true });
      }

      this.db = new DatabaseSync(this.dbPath);
      this.isAvailable = true;

      this.createSchema();
      console.log('[SQLite] Primary storage initialized');
      return true;
    } catch (err) {
      console.error('[SQLite] Initialization failed:', err.message);
      this.isAvailable = false;
      return false;
    }
  }

  createSchema() {
    if (!this.db) return;

    this.db.exec(`
      CREATE TABLE IF NOT EXISTS memories (
        id TEXT PRIMARY KEY,
        content TEXT NOT NULL,
        tags TEXT DEFAULT '[]',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        importance INTEGER DEFAULT 50,
        strength REAL DEFAULT 1.0,
        access_count INTEGER DEFAULT 0,
        source TEXT DEFAULT 'user',
        version INTEGER DEFAULT 1
      );

      CREATE TABLE IF NOT EXISTS embeddings (
        memory_id TEXT PRIMARY KEY,
        embedding BLOB,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
      );

      CREATE TABLE IF NOT EXISTS access_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        memory_id TEXT,
        accessed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        context TEXT,
        FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
      );

      CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance);
      CREATE INDEX IF NOT EXISTS idx_memories_updated ON memories(updated_at);
      CREATE INDEX IF NOT EXISTS idx_access_log_memory ON access_log(memory_id);

      CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
        id,
        content,
        tags,
        content='memories',
        content_rowid='rowid'
      );
    `);
  }

  insert(memory) {
    if (!this.isAvailable) return false;

    try {
      const stmt = this.db.prepare(`
        INSERT OR REPLACE INTO memories 
        (id, content, tags, created_at, updated_at, importance, strength, access_count, source, version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `);

      stmt.run(
        memory.id,
        memory.content,
        JSON.stringify(memory.tags || []),
        memory.createdAt,
        memory.updatedAt,
        memory.importance || 50,
        memory.strength || 1.0,
        memory.accessCount || 0,
        memory.source || 'user',
        memory.version || 1
      );

      this.db.prepare(`
        INSERT OR REPLACE INTO memories_fts (id, content, tags)
        VALUES (?, ?, ?)
      `).run(memory.id, memory.content, (memory.tags || []).join(' '));

      return true;
    } catch (err) {
      console.error('[SQLite] Insert error:', err.message);
      return false;
    }
  }

  get(id) {
    if (!this.isAvailable) return null;

    try {
      const row = this.db.prepare('SELECT * FROM memories WHERE id = ?').get(id);
      return row ? this.rowToMemory(row) : null;
    } catch (err) {
      console.error('[SQLite] Get error:', err.message);
      return null;
    }
  }

  getAll() {
    if (!this.isAvailable) return [];

    try {
      const rows = this.db.prepare('SELECT * FROM memories ORDER BY updated_at DESC').all();
      return rows.map(r => this.rowToMemory(r));
    } catch (err) {
      console.error('[SQLite] GetAll error:', err.message);
      return [];
    }
  }

  delete(id) {
    if (!this.isAvailable) return false;

    try {
      this.db.prepare('DELETE FROM memories WHERE id = ?').run(id);
      return true;
    } catch (err) {
      console.error('[SQLite] Delete error:', err.message);
      return false;
    }
  }

  update(id, updates) {
    if (!this.isAvailable) return false;

    try {
      const fields = [];
      const values = [];

      if (updates.content !== undefined) {
        fields.push('content = ?');
        values.push(updates.content);
      }
      if (updates.tags !== undefined) {
        fields.push('tags = ?');
        values.push(JSON.stringify(updates.tags));
      }
      if (updates.importance !== undefined) {
        fields.push('importance = ?');
        values.push(updates.importance);
      }
      if (updates.strength !== undefined) {
        fields.push('strength = ?');
        values.push(updates.strength);
      }
      if (updates.accessCount !== undefined) {
        fields.push('access_count = ?');
        values.push(updates.accessCount);
      }

      fields.push('updated_at = ?');
      values.push(new Date().toISOString());
      values.push(id);

      const sql = `UPDATE memories SET ${fields.join(', ')} WHERE id = ?`;
      this.db.prepare(sql).run(...values);

      if (updates.content !== undefined || updates.tags !== undefined) {
        const memory = this.get(id);
        if (memory) {
          this.db.prepare(`
            INSERT OR REPLACE INTO memories_fts (id, content, tags)
            VALUES (?, ?, ?)
          `).run(id, memory.content, (memory.tags || []).join(' '));
        }
      }

      return true;
    } catch (err) {
      console.error('[SQLite] Update error:', err.message);
      return false;
    }
  }

  search(query, options = {}) {
    if (!this.isAvailable) return [];

    const { limit = 20 } = options;

    try {
      let rows;
      try {
        rows = this.db.prepare(`
          SELECT m.* FROM memories m
          JOIN memories_fts fts ON m.id = fts.id
          WHERE memories_fts MATCH ?
          ORDER BY rank
          LIMIT ?
        `).all(query, limit);
      } catch (ftsErr) {
        const pattern = `%${query}%`;
        rows = this.db.prepare(`
          SELECT * FROM memories 
          WHERE content LIKE ? OR tags LIKE ? OR id LIKE ?
          ORDER BY updated_at DESC
          LIMIT ?
        `).all(pattern, pattern, pattern, limit);
      }

      return rows.map(r => this.rowToMemory(r));
    } catch (err) {
      console.error('[SQLite] Search error:', err.message);
      return [];
    }
  }

  getByTag(tag) {
    if (!this.isAvailable) return [];

    try {
      const rows = this.db.prepare(`
        SELECT * FROM memories 
        WHERE tags LIKE ?
        ORDER BY updated_at DESC
      `).all(`%"${tag}"%`);

      return rows.map(r => this.rowToMemory(r));
    } catch (err) {
      console.error('[SQLite] GetByTag error:', err.message);
      return [];
    }
  }

  saveEmbedding(memoryId, embedding) {
    if (!this.isAvailable) return false;

    try {
      const buffer = Buffer.from(new Float32Array(embedding).buffer);
      this.db.prepare(`
        INSERT OR REPLACE INTO embeddings (memory_id, embedding, updated_at)
        VALUES (?, ?, ?)
      `).run(memoryId, buffer, new Date().toISOString());
      return true;
    } catch (err) {
      console.error('[SQLite] SaveEmbedding error:', err.message);
      return false;
    }
  }

  getEmbedding(memoryId) {
    if (!this.isAvailable) return null;

    try {
      const row = this.db.prepare('SELECT embedding FROM embeddings WHERE memory_id = ?').get(memoryId);
      if (!row || !row.embedding) return null;
      
      const floatArray = new Float32Array(row.embedding.buffer, row.embedding.byteOffset, row.embedding.byteLength / 4);
      return Array.from(floatArray);
    } catch (err) {
      console.error('[SQLite] GetEmbedding error:', err.message);
      return null;
    }
  }

  getAllEmbeddings() {
    if (!this.isAvailable) return new Map();

    try {
      const rows = this.db.prepare('SELECT memory_id, embedding FROM embeddings').all();
      const embeddings = new Map();
      
      for (const row of rows) {
        if (row.embedding) {
          const floatArray = new Float32Array(row.embedding.buffer, row.embedding.byteOffset, row.embedding.byteLength / 4);
          embeddings.set(row.memory_id, Array.from(floatArray));
        }
      }
      
      return embeddings;
    } catch (err) {
      console.error('[SQLite] GetAllEmbeddings error:', err.message);
      return new Map();
    }
  }

  getStats() {
    if (!this.isAvailable) return { total: 0, withEmbeddings: 0 };

    try {
      const memCount = this.db.prepare('SELECT COUNT(*) as count FROM memories').get().count;
      const embCount = this.db.prepare('SELECT COUNT(*) as count FROM embeddings').get().count;
      
      return {
        total: memCount,
        withEmbeddings: embCount
      };
    } catch (err) {
      console.error('[SQLite] Stats error:', err.message);
      return { total: 0, withEmbeddings: 0 };
    }
  }

  rowToMemory(row) {
    return {
      id: row.id,
      content: row.content,
      tags: JSON.parse(row.tags || '[]'),
      createdAt: row.created_at,
      updatedAt: row.updated_at,
      importance: row.importance,
      strength: row.strength,
      accessCount: row.access_count,
      source: row.source,
      version: row.version
    };
  }
}
