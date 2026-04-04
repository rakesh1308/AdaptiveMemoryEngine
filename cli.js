#!/usr/bin/env node
/**
 * AdaptiveMemoryEngine CLI
 * 
 * Import files, manage memories, interact with the system
 * 
 * Provider Configuration:
 *   Set PROVIDER_TYPE environment variable:
 *     openai (default), ollama, gemini
 *   
 *   Or use .env file with provider-specific vars:
 *     OPENAI_API_KEY=...
 *     OLLAMA_HOST=http://localhost:11434
 *     GEMINI_API_KEY=...
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { MemoryEngine } from './src/index.js';
import { ProviderFactory } from './src/utils/ProviderFactory.js';
import { AnthropicProvider } from './src/utils/AnthropicProvider.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = process.env.DATA_DIR || path.join(__dirname, 'data');

// Provider setup
const PROVIDER_TYPE = process.env.PROVIDER_TYPE || 'openai';
const INTELLIGENCE_PROVIDER = process.env.INTELLIGENCE_PROVIDER;

function createProviders() {
  // Create embedding provider
  const embeddingProvider = ProviderFactory.create({
    type: PROVIDER_TYPE,
    embeddingModel: process.env.EMBEDDING_MODEL || process.env.OPENAI_EMBEDDING_MODEL,
    chatModel: process.env.CHAT_MODEL || process.env.OPENAI_CHAT_MODEL
  });

  if (!embeddingProvider.isAvailable()) {
    console.error(`❌ Provider ${PROVIDER_TYPE} is not available.`);
    console.error(`   Check your API keys and configuration.`);
    console.error(`   Provider config:`, embeddingProvider.getConfig?.() || 'N/A');
    process.exit(1);
  }

  // Intelligence provider
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

console.error(`[CLI] Provider: ${PROVIDER_TYPE}`);
if (INTELLIGENCE_PROVIDER && INTELLIGENCE_PROVIDER !== PROVIDER_TYPE) {
  console.error(`[CLI] Intelligence: ${INTELLIGENCE_PROVIDER}`);
}

const engine = new MemoryEngine({
  dataDir: DATA_DIR,
  embeddingProvider,
  intelligenceProvider
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

  case 'ask': {
    const question = args.join(' ');
    if (!question) {
      console.log('Usage: cli.js ask <question>');
      process.exit(1);
    }
    
    const results = await engine.searchMemories(question, { topK: 3, mode: 'hybrid' });
    if (results.length === 0) {
      console.log('No relevant memories found.');
      break;
    }
    
    const context = results.map(r => r.memory.content).join('\n\n---\n\n');
    const answer = await intelligenceProvider.synthesize(context, question, 'detailed');
    
    console.log(`\nQ: ${question}\n`);
    console.log(answer);
    console.log(`\n---\nSources: ${results.map(r => r.memory.id).join(', ')}`);
    break;
  }

  case 'provider': {
    const embConfig = embeddingProvider.getConfig?.() || { type: PROVIDER_TYPE };
    const intConfig = intelligenceProvider.getConfig?.() || { type: INTELLIGENCE_PROVIDER || PROVIDER_TYPE };
    
    console.log('\n🤖 Provider Configuration\n');
    console.log(`Embeddings: ${embConfig.type}`);
    console.log(`  Model: ${embConfig.embeddingModel || 'default'}`);
    console.log(`  Available: ${embeddingProvider.isAvailable() ? '✅' : '❌'}`);
    if (embConfig.baseUrl) console.log(`  URL: ${embConfig.baseUrl}`);
    
    console.log(`\nIntelligence: ${intConfig.type}`);
    console.log(`  Model: ${intConfig.model || intConfig.chatModel || 'default'}`);
    console.log(`  Available: ${intelligenceProvider.isAvailable() ? '✅' : '❌'}`);
    break;
  }

  case 'help':
  default:
    console.log(`
🧠 AdaptiveMemoryEngine CLI

Provider: ${PROVIDER_TYPE}${INTELLIGENCE_PROVIDER ? ` + ${INTELLIGENCE_PROVIDER}` : ''}

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
  ask <question>                    Ask AI about your memories
  provider                          Show provider configuration
  help                              Show this help

Environment:
  PROVIDER_TYPE=openai|ollama|gemini  AI provider type
  INTELLIGENCE_PROVIDER=anthropic     Optional separate intelligence provider
  DATA_DIR=./data                     Data directory
  OPENAI_API_KEY=...                  OpenAI API key
  OLLAMA_HOST=http://localhost:11434  Ollama server URL
  GEMINI_API_KEY=...                  Gemini API key
  ANTHROPIC_API_KEY=...               Anthropic API key (for intelligence)

Examples:
  # Use OpenAI (default)
  OPENAI_API_KEY=sk-... cli.js import notes.md

  # Use local Ollama
  PROVIDER_TYPE=ollama cli.js import notes.md

  # Use OpenAI embeddings + Anthropic intelligence
  OPENAI_API_KEY=... ANTHROPIC_API_KEY=... INTELLIGENCE_PROVIDER=anthropic cli.js ask "summarize my notes"
`);
}

process.exit(0);
