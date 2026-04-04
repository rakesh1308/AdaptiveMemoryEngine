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

// PDF support (optional)
let PDFParser;
try {
  const pdfModule = await import('pdf2json');
  PDFParser = pdfModule.default || pdfModule;
} catch {
  PDFParser = null;
}

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

async function extractTextFromFile(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  
  // PDF files
  if (ext === '.pdf') {
    if (!PDFParser) {
      throw new Error('PDF parsing not available. Install pdf2json: npm install pdf2json');
    }
    
    return new Promise((resolve, reject) => {
      const pdfParser = new PDFParser();
      
      pdfParser.on('pdfParser_dataError', err => {
        reject(new Error(`PDF parse error: ${err.parserError}`));
      });
      
      pdfParser.on('pdfParser_dataReady', pdfData => {
        // Extract text from all pages
        let text = '';
        if (pdfData.Pages) {
          for (const page of pdfData.Pages) {
            if (page.Texts) {
              for (const textItem of page.Texts) {
                if (textItem.R) {
                  for (const r of textItem.R) {
                    if (r.T) {
                      try {
                        text += decodeURIComponent(r.T) + ' ';
                      } catch {
                        text += r.T + ' ';
                      }
                    }
                  }
                }
              }
            }
            text += '\n\n';
          }
        }
        resolve(`PDF: ${path.basename(filePath)}\n\n${text.trim()}`);
      });
      
      pdfParser.loadPDF(filePath);
    });
  }
  
  // Text files (default)
  return fs.readFileSync(filePath, 'utf-8');
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
      console.log('');
      console.log('Examples:');
      console.log('  cli.js import ./notes.md');
      console.log('  cli.js import "C:\\My Documents\\file.md"  <-- Note the quotes for paths with spaces');
      console.log('  cli.js import ./docs -r --tag work');
      process.exit(1);
    }

    const recursive = args.includes('-r') || args.includes('--recursive');
    const tagIndex = args.findIndex(a => a === '--tag' || a === '-t');
    const tags = tagIndex !== -1 && args[tagIndex + 1]
      ? args[tagIndex + 1].split(',').map(t => t.trim())
      : [];

    // Check if file exists
    let stats;
    try {
      stats = fs.statSync(filePath);
    } catch (err) {
      if (err.code === 'ENOENT') {
        console.error(`❌ File not found: ${filePath}`);
        // Simple hint - if path looks like it was split
        const fullCmd = process.argv.slice(2).join(' ');
        if (fullCmd.includes('import ') && !filePath.includes('.') && args[1] && args[1].includes('.')) {
          console.error('');
          console.error('💡 Hint: Your path may contain spaces. Use quotes:');
          console.error(`   cli.js import "${filePath} ${args.slice(1).join(' ').split(' --')[0]}"`);
        }
        process.exit(1);
      }
      throw err;
    }

    // Supported file types for import
    const supportedExtensions = ['.md', '.txt', '.pdf', '.js', '.ts', '.jsx', '.tsx', '.py', '.java', '.go', '.rs', '.c', '.cpp', '.h', '.cs', '.rb', '.php', '.swift', '.kt', '.scala', '.r', '.m', '.mm', '.sql', '.sh', '.bash', '.zsh', '.ps1', '.yaml', '.yml', '.json', '.xml', '.html', '.htm', '.css', '.scss', '.sass', '.less', '.vue', '.svelte', '.astro', '.mdx', '.rst', '.adoc', '.tex', '.csv', '.tsv', '.log', '.ini', '.conf', '.cfg', '.properties', '.env'];
    
    if (stats.isDirectory()) {
      const files = [];
      const entries = fs.readdirSync(filePath, { withFileTypes: true, recursive });

      for (const entry of entries) {
        if (entry.isFile()) {
          const ext = path.extname(entry.name).toLowerCase();
          const name = entry.name.toLowerCase();
          // Check by extension or special filenames (Dockerfile, Makefile, etc.)
          if (supportedExtensions.includes(ext) || 
              name === 'dockerfile' || 
              name === 'makefile' || 
              name === 'gemfile' ||
              name === 'rakefile' ||
              name === 'jenkinsfile' ||
              name.startsWith('dockerfile.') ||
              name === '.gitignore' ||
              name === '.editorconfig' ||
              name === '.eslintrc' ||
              name === '.prettierrc') {
            files.push(path.join(entry.parentPath || filePath, entry.name));
          }
        }
      }

      console.log(`Found ${files.length} files to import...\n`);

      for (const file of files) {
        try {
          const content = await extractTextFromFile(file);
          const id = makeKey(file);
          await engine.storeMemory(id, content, { tags });
          console.log(`✅ ${id}`);
        } catch (err) {
          console.error(`❌ Failed to import ${path.basename(file)}: ${err.message}`);
        }
      }

      console.log(`\nImported ${files.length} files`);
    } else {
      // Single file import - check extension
      const ext = path.extname(filePath).toLowerCase();
      const supportedExtensions = ['.md', '.txt', '.pdf', '.js', '.ts', '.jsx', '.tsx', '.py', '.java', '.go', '.rs', '.c', '.cpp', '.h', '.cs', '.rb', '.php', '.swift', '.kt', '.scala', '.r', '.m', '.mm', '.sql', '.sh', '.bash', '.zsh', '.ps1', '.yaml', '.yml', '.json', '.xml', '.html', '.htm', '.css', '.scss', '.sass', '.less', '.vue', '.svelte', '.astro', '.mdx', '.rst', '.adoc', '.tex', '.csv', '.tsv', '.log', '.ini', '.conf', '.cfg', '.properties', '.env'];
      const name = path.basename(filePath).toLowerCase();
      const isSupported = supportedExtensions.includes(ext) || 
        ['dockerfile', 'makefile', 'gemfile', 'rakefile', 'jenkinsfile'].includes(name) ||
        name.startsWith('dockerfile.') ||
        name.startsWith('.') ||  // Hidden config files
        !ext;  // Files without extension (scripts)
      
      if (!isSupported) {
        console.warn(`⚠️  Warning: File type "${ext || name}" may not be text-based.`);
        console.warn(`   Supported: .md .txt .js .ts .py .java .go and 50+ more`);
        console.warn(`   Use at your own risk or convert to text first.`);
      }
      
      const content = await extractTextFromFile(filePath);
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

Supported File Types for Import:
  Documents:  .md .mdx .txt .pdf .rst .adoc .tex .csv .tsv .log
  Code:       .js .ts .jsx .tsx .py .java .go .rs .c .cpp .h
              .cs .rb .php .swift .kt .scala .r .m .mm .sql
              .sh .bash .zsh .ps1 .vue .svelte .astro .html
              .htm .css .scss .sass .less
  Config:     .json .xml .yaml .yml .ini .conf .cfg .properties
              .env .tf .hcl Dockerfile Makefile
  Other:      .gitignore .editorconfig .eslintrc .prettierrc

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
