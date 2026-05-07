#!/usr/bin/env node
/**
 * Import memories from a JSONL backup file into AdaptiveMemoryEngine
 * 
 * Usage: node import-backup.js <path-to-jsonl-file>
 * 
 * The JSONL file should have one JSON object per line, where each object
 * has at minimum: { id, content, [tags] }
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { MemoryEngine } from './src/index.js';
import { ProviderFactory } from './src/utils/ProviderFactory.js';
import { AnthropicProvider } from './src/utils/AnthropicProvider.js';
import readline from 'readline';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const backupFile = process.argv[2];
if (!backupFile) {
  console.error('Usage: node import-backup.js <path-to-jsonl-file>');
  process.exit(1);
}

if (!fs.existsSync(backupFile)) {
  console.error(`❌ File not found: ${backupFile}`);
  process.exit(1);
}

const DATA_DIR = process.env.DATA_DIR || path.join(__dirname, 'data');
const PROVIDER_TYPE = process.env.PROVIDER_TYPE || 'openai';
const INTELLIGENCE_PROVIDER = process.env.INTELLIGENCE_PROVIDER;

function createProviders() {
  const embeddingProvider = ProviderFactory.create({
    type: PROVIDER_TYPE,
    embeddingModel: process.env.EMBEDDING_MODEL || process.env.OPENAI_EMBEDDING_MODEL,
    chatModel: process.env.CHAT_MODEL || process.env.OPENAI_CHAT_MODEL
  });

  if (!embeddingProvider.isAvailable()) {
    console.error(`❌ Provider ${PROVIDER_TYPE} is not available.`);
    console.error(`   Check your API keys and configuration.`);
    process.exit(1);
  }

  let intelligenceProvider = embeddingProvider;
  
  if (INTELLIGENCE_PROVIDER && INTELLIGENCE_PROVIDER !== PROVIDER_TYPE) {
    if (INTELLIGENCE_PROVIDER === 'anthropic') {
      intelligenceProvider = new AnthropicProvider({
        embeddingFallback: embeddingProvider
      });
    } else {
      intelligenceProvider = ProviderFactory.create({ type: INTELLIGENCE_PROVIDER });
    }
  }

  return { embeddingProvider, intelligenceProvider };
}

const { embeddingProvider, intelligenceProvider } = createProviders();

console.error(`[Import] Provider: ${PROVIDER_TYPE}`);
console.error(`[Import] Loading backup from: ${backupFile}`);

const engine = new MemoryEngine({
  dataDir: DATA_DIR,
  embeddingProvider,
  intelligenceProvider
});

await engine.initialize();

// Read JSONL file line by line
const memories = [];
const fileStream = fs.createReadStream(backupFile);
const rl = readline.createInterface({
  input: fileStream,
  crlfDelay: Infinity
});

for await (const line of rl) {
  if (!line.trim()) continue;
  try {
    const memory = JSON.parse(line);
    if (memory.id && memory.content) {
      memories.push(memory);
    }
  } catch (e) {
    console.error(`⚠️  Skipping invalid JSON line: ${e.message.substring(0, 50)}...`);
  }
}

console.log(`\n📦 Found ${memories.length} memories in backup file\n`);

// Import memories
let imported = 0;
let skipped = 0;
let errors = 0;

for (let i = 0; i < memories.length; i++) {
  const m = memories[i];
  
  // Check if memory already exists
  const existing = engine.memories.get(m.id);
  if (existing) {
    console.log(`⏭️  [${i + 1}/${memories.length}] Skipping (already exists): ${m.id}`);
    skipped++;
    continue;
  }

  try {
    const tags = m.tags || [];
    await engine.storeMemory(m.id, m.content, { 
      tags,
      autoTag: false,
      source: 'import'
    });
    imported++;
    
    if (imported % 10 === 0 || i === memories.length - 1) {
      console.log(`✅ [${i + 1}/${memories.length}] Imported: ${m.id} (${imported} so far)`);
    }
    
    // Small delay to avoid rate limiting
    await new Promise(resolve => setTimeout(resolve, 20));
  } catch (err) {
    errors++;
    console.error(`❌ [${i + 1}/${memories.length}] Failed: ${m.id} - ${err.message}`);
  }
}

console.log(`\n📊 Import Summary:`);
console.log(`   Total in backup: ${memories.length}`);
console.log(`   Imported: ${imported}`);
console.log(`   Skipped (already exist): ${skipped}`);
console.log(`   Errors: ${errors}`);

// Show final stats
const stats = engine.getStats();
console.log(`\n📊 Engine Stats:`);
console.log(`   Total memories: ${stats.totalMemories}`);
console.log(`   Total embeddings: ${stats.totalEmbeddings}`);
console.log(`   Total concepts: ${stats.totalConcepts}`);

process.exit(errors > 0 ? 1 : 0);