#!/usr/bin/env node
/**
 * AdaptiveMemoryEngine CLI
 * 
 * Import files, manage memories, interact with the system
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { MemoryEngine, OpenAIProvider } from './src/index.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = process.env.DATA_DIR || path.join(__dirname, 'data');

if (!process.env.OPENAI_API_KEY) {
  console.error('❌ OPENAI_API_KEY is required. Set it in your environment.');
  process.exit(1);
}

const embeddingProvider = new OpenAIProvider({
  apiKey: process.env.OPENAI_API_KEY,
  embeddingModel: process.env.OPENAI_EMBEDDING_MODEL || 'text-embedding-3-small',
  chatModel: process.env.OPENAI_CHAT_MODEL || 'gpt-4o-mini'
});

const engine = new MemoryEngine({
  dataDir: DATA_DIR,
  embeddingProvider,
  intelligenceProvider: embeddingProvider
});

await engine.initialize();

function makeKey(filename) {
  return path.basename(filename, path.extname(filename))
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

function formatMemory(m) {
  const preview = m.content.substring(0, 80).replace(/\n/g, ' ');
  return `• ${m.id}\n  Tags: ${m.tags?.join(', ') || 'none'}\n  ${preview}...`;
}

const command = process.argv[2];
const args = process.argv.slice(3);

switch (command) {
  case 'import': {
    const filePath = args[0];
    if (!filePath) {
      console.log('Usage: cli.js import <file-or-directory> [--recursive] [--tag tag1,tag2]');
      process.exit(1);
    }

    const recursive = args.includes('-r') || args.includes('--recursive');
    const tagIndex = args.findIndex(a => a === '--tag' || a === '-t');
    const tags = tagIndex !== -1 && args[tagIndex + 1]
      ? args[tagIndex + 1].split(',').map(t => t.trim())
      : [];

    const stats = fs.statSync(filePath);

    if (stats.isDirectory()) {
      const files = [];
      const entries = fs.readdirSync(filePath, { withFileTypes: true, recursive });

      for (const entry of entries) {
        if (entry.isFile() && (entry.name.endsWith('.md') || entry.name.endsWith('.txt'))) {
          files.push(path.join(entry.parentPath || filePath, entry.name));
        }
      }

      console.log(`Found ${files.length} files to import...\n`);

      for (const file of files) {
        const content = fs.readFileSync(file, 'utf-8');
        const id = makeKey(file);
        await engine.storeMemory(id, content, { tags });
        console.log(`✅ ${id}`);
      }

      console.log(`\nImported ${files.length} files`);
    } else {
      const content = fs.readFileSync(filePath, 'utf-8');
      const id = makeKey(filePath);
      await engine.storeMemory(id, content, { tags });
      console.log(`✅ Imported: ${id}`);
    }
    break;
  }

  case 'list': {
    const filter = args[0];
    const memories = engine.listMemories({ filter });

    console.log(`\n${memories.length} memories:\n`);
    for (const m of memories) {
      console.log(formatMemory(m));
      console.log();
    }
    break;
  }

  case 'search': {
    const query = args.join(' ');
    if (!query) {
      console.log('Usage: cli.js search <query>');
      process.exit(1);
    }

    const results = await engine.searchMemories(query, {
      topK: 20,
      mode: 'hybrid'
    });

    console.log(`\n${results.length} results for "${query}":\n`);
    for (const r of results) {
      console.log(`• ${r.memory.id} [${r.method}]`);
      console.log(`  ${r.memory.content.substring(0, 100)}...\n`);
    }
    break;
  }

  case 'get': {
    const id = args[0];
    if (!id) {
      console.log('Usage: cli.js get <id>');
      process.exit(1);
    }

    const memory = await engine.recallMemory(id);
    if (memory) {
      console.log(`\n# ${memory.id}\n`);
      console.log(memory.content);
      console.log(`\n---\nTags: ${memory.tags?.join(', ') || 'none'}`);
      console.log(`Created: ${memory.createdAt}`);
    } else {
      console.log('Memory not found');
    }
    break;
  }

  case 'delete': {
    const id = args[0];
    if (!id) {
      console.log('Usage: cli.js delete <id>');
      process.exit(1);
    }

    const result = await engine.deleteMemory(id);
    console.log(result.deleted ? `✅ Deleted: ${id}` : `❌ ${result.error}`);
    break;
  }

  case 'stats': {
    const stats = engine.getStats();
    console.log('\n📊 Statistics\n');
    console.log(`Total memories: ${stats.totalMemories}`);
    console.log(`Total chunks: ${stats.totalChunks}`);
    console.log(`Total embeddings: ${stats.totalEmbeddings}`);
    console.log(`Total concepts: ${stats.totalConcepts}`);
    console.log(`Average importance: ${stats.avgImportance}`);
    console.log(`Intelligence: ${stats.intelligenceEnabled ? 'ON' : 'OFF'}`);
    console.log(`Storage: ${stats.storage.primary}`);
    break;
  }

  case 'export': {
    const memories = engine.export();
    const outputFile = args[0] || `export-${Date.now()}.json`;
    fs.writeFileSync(outputFile, JSON.stringify({
      exportedAt: new Date().toISOString(),
      count: memories.memories.length,
      ...memories
    }, null, 2));
    console.log(`✅ Exported to ${outputFile}`);
    break;
  }

  case 'snapshot': {
    const snapshotPath = await engine.createSnapshot();
    console.log(`✅ Snapshot: ${snapshotPath}`);
    break;
  }

  case 'graph': {
    const concept = args[0];
    if (!concept) {
      console.log('Usage: cli.js graph <concept>');
      process.exit(1);
    }
    const related = engine.knowledgeGraph.getRelatedConcepts(concept, 2);
    console.log(`\nConcept: ${concept}`);
    console.log(`Related (${related.length - 1}):`);
    for (const r of related.slice(1)) {
      console.log(`  • ${r.concept} (${(r.strength * 100).toFixed(0)}%)`);
    }
    break;
  }

  case 'help':
  default:
    console.log(`
🧠 AdaptiveMemoryEngine CLI

Commands:
  import <path> [-r] [--tag t1,t2]  Import file or directory
  list [filter]                     List all memories
  search <query>                    Search memories (hybrid semantic + keyword)
  get <id>                          Get memory by ID
  delete <id>                       Delete a memory
  stats                             Show statistics
  export [file]                     Export to JSON
  snapshot                          Create backup
  graph <concept>                   Query knowledge graph
  help                              Show this help

Environment:
  DATA_DIR=./data                   Data directory
  OPENAI_API_KEY=sk-...             Required for embeddings
  OPENAI_CHAT_MODEL=gpt-4o-mini     Optional intelligence model

Examples:
  cli.js import notes.md
  cli.js import ./docs -r --tag documentation
  cli.js search "javascript"
  cli.js graph "machine learning"
`);
}

process.exit(0);
