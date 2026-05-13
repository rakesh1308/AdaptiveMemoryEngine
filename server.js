#!/usr/bin/env node
/**
 * AdaptiveMemoryEngine MCP Server
 * 
 * Transport modes:
 *   stdio (default)        - For local MCP clients like Claude Desktop
 *   http                   - For remote deployment via Streamable HTTP
 * 
 * Provider configuration (choose one):
 *   OpenAI (default):
 *     OPENAI_API_KEY=sk-...
 *   
 *   Ollama (local):
 *     PROVIDER_TYPE=ollama
 *     OLLAMA_HOST=http://localhost:11434
 *     OLLAMA_EMBEDDING_MODEL=nomic-embed-text
 *     OLLAMA_CHAT_MODEL=llama3.2
 *   
 *   Google Gemini:
 *     PROVIDER_TYPE=gemini
 *     GEMINI_API_KEY=...
 *   
 *   Mixed (Anthropic intelligence + OpenAI embeddings):
 *     PROVIDER_TYPE=openai
 *     OPENAI_API_KEY=...
 *     ANTHROPIC_API_KEY=...
 *     INTELLIGENCE_PROVIDER=anthropic
 * 
 * Usage:
 *   node server.js                         # stdio mode
 *   TRANSPORT=http PORT=3000 node server.js  # Streamable HTTP mode
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { isInitializeRequest } from '@modelcontextprotocol/sdk/types.js';
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
  ErrorCode,
  McpError
} from '@modelcontextprotocol/sdk/types.js';
import express from 'express';
import path from 'path';
import { fileURLToPath } from 'url';
import { randomUUID } from 'node:crypto';
import { readFileSync } from 'fs';

// Load .env file if it exists (for local development)
try {
  const envFile = path.join(__dirname, '.env');
  const envContent = readFileSync(envFile, 'utf-8');
  envContent.split('\n').forEach(line => {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) return;
    
    const eqIndex = trimmed.indexOf('=');
    if (eqIndex <= 0) return;
    
    const key = trimmed.substring(0, eqIndex).trim();
    const value = trimmed.substring(eqIndex + 1).trim();
    
    // Skip placeholder values - don't override Railway-injected real values
    const isPlaceholder = value.includes('YOUR-KEY-HERE') || value.includes('****');
    
    if (!process.env[key]) {
      process.env[key] = value;
    }
  });
  console.error('[Config] .env file loaded (if present)');
} catch (e) {
  // .env file not found - likely in production (Railway injects env vars)
}

// Debug: Log environment configuration
console.error(`[Config] PROVIDER_TYPE: ${process.env.PROVIDER_TYPE || 'not set'}`);
console.error(`[Config] OPENAI_API_KEY: ${process.env.OPENAI_API_KEY ? '***' + process.env.OPENAI_API_KEY.slice(-4) : 'not set'}`);
console.error(`[Config] TRANSPORT: ${process.env.TRANSPORT || 'not set'}`);
console.error(`[Config] DATA_DIR: ${process.env.DATA_DIR || 'not set'}`);

import { MemoryEngine } from './src/core/MemoryEngine.js';
import { ProviderFactory } from './src/utils/ProviderFactory.js';
import { AnthropicProvider } from './src/utils/AnthropicProvider.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// ==================== LOG REDIRECT FOR MCP ====================
// MCP stdio transport requires stdout to be clean JSON only.
// Redirect all console.log to stderr so logs don't break the protocol.
const originalLog = console.log;
console.log = (...args) => console.error(...args);

// ==================== CONFIGURATION ====================
const PORT = process.env.PORT || 3000;
const DATA_DIR = process.env.DATA_DIR || path.join(__dirname, 'data');
const TRANSPORT = process.env.TRANSPORT || 'stdio';

// Provider configuration
const PROVIDER_TYPE = process.env.PROVIDER_TYPE || 'openai';
const EMBEDDING_MODEL = process.env.EMBEDDING_MODEL || process.env.OPENAI_EMBEDDING_MODEL || 'text-embedding-3-small';
const CHAT_MODEL = process.env.CHAT_MODEL || process.env.OPENAI_CHAT_MODEL || 'gpt-4o-mini';

// Optional: Separate intelligence provider
const INTELLIGENCE_PROVIDER = process.env.INTELLIGENCE_PROVIDER;

// ==================== PROVIDER SETUP ====================
function createProviders() {
  // Create embedding provider
  let embeddingProvider = null;
  let intelligenceProvider = null;
  
  try {
    embeddingProvider = ProviderFactory.create({
      type: PROVIDER_TYPE,
      embeddingModel: EMBEDDING_MODEL,
      chatModel: CHAT_MODEL
    });

    if (!embeddingProvider.isAvailable()) {
      console.error(`[Provider] ${PROVIDER_TYPE} is not available - running without AI features`);
      embeddingProvider = null;
    }
  } catch (error) {
    console.error(`[Provider] Failed to initialize ${PROVIDER_TYPE}: ${error.message}`);
    embeddingProvider = null;
  }

  // Intelligence provider (can be same or different)
  if (embeddingProvider) {
    intelligenceProvider = embeddingProvider;
    
    if (INTELLIGENCE_PROVIDER && INTELLIGENCE_PROVIDER !== PROVIDER_TYPE) {
      try {
        if (INTELLIGENCE_PROVIDER === 'anthropic') {
          intelligenceProvider = new AnthropicProvider({
            embeddingFallback: embeddingProvider
          });
        } else {
          intelligenceProvider = ProviderFactory.create({ type: INTELLIGENCE_PROVIDER });
        }
      } catch (error) {
        console.error(`[Provider] Failed to initialize intelligence provider ${INTELLIGENCE_PROVIDER}: ${error.message}`);
        intelligenceProvider = embeddingProvider;
      }
    }
  }

  return { embeddingProvider, intelligenceProvider };
}

// ==================== INITIALIZATION ====================
const { embeddingProvider, intelligenceProvider } = createProviders();

console.error(`[AdaptiveMemoryEngine] Provider: ${PROVIDER_TYPE}`);
if (INTELLIGENCE_PROVIDER && INTELLIGENCE_PROVIDER !== PROVIDER_TYPE) {
  console.error(`[AdaptiveMemoryEngine] Intelligence: ${INTELLIGENCE_PROVIDER}`);
}

const engine = new MemoryEngine({
  dataDir: DATA_DIR,
  embeddingProvider,
  intelligenceProvider
});

await engine.initialize();

const stats = engine.getStats();
console.error(`[AdaptiveMemoryEngine] Initialized: ${stats.totalMemories} memories, ${stats.totalConcepts} concepts`);

// ==================== MCP SERVER SETUP ====================
// Tool definitions (module scope)
const toolDefinitions = [
  {
    name: 'store_memory',
    description: 'Store a memory with automatic embeddings. Auto-tags with AI if available.',
    inputSchema: {
      type: 'object',
      properties: {
        key: { type: 'string' },
        content: { type: 'string' },
        tags: { type: 'array', items: { type: 'string' } },
        auto_tag: { type: 'boolean' }
      },
      required: ['key', 'content']
    }
  },
  {
    name: 'get_memory',
    description: 'Get memory by key',
    inputSchema: {
      type: 'object',
      properties: { key: { type: 'string' } },
      required: ['key']
    }
  },
  {
    name: 'update_memory',
    description: 'Update memory content and/or tags',
    inputSchema: {
      type: 'object',
      properties: {
        key: { type: 'string' },
        content: { type: 'string' },
        tags: { type: 'array', items: { type: 'string' } },
        merge_tags: { type: 'boolean' }
      },
      required: ['key']
    }
  },
  {
    name: 'delete_memory',
    description: 'Delete a memory',
    inputSchema: {
      type: 'object',
      properties: { key: { type: 'string' } },
      required: ['key']
    }
  },
  {
    name: 'search',
    description: 'Semantic + keyword hybrid search',
    inputSchema: {
      type: 'object',
      properties: {
        query: { type: 'string' },
        limit: { type: 'number' }
      },
      required: ['query']
    }
  },
  {
    name: 'list_memories',
    description: 'List all memories, optionally filter by tag',
    inputSchema: {
      type: 'object',
      properties: {
        filter: { type: 'string' },
        limit: { type: 'number' }
      }
    }
  },
  {
    name: 'query_graph',
    description: 'Query the knowledge graph for related concepts and memories',
    inputSchema: {
      type: 'object',
      properties: {
        concept: { type: 'string' },
        depth: { type: 'number' },
        find_path_to: { type: 'string' }
      }
    }
  },
  {
    name: 'get_stats',
    description: 'System statistics',
    inputSchema: { type: 'object' }
  },
  {
    name: 'backup',
    description: 'Create a backup snapshot',
    inputSchema: { type: 'object' }
  },
  {
    name: 'smart_search',
    description: 'AI-enhanced hybrid search (same as search since embeddings are mandatory)',
    inputSchema: {
      type: 'object',
      properties: {
        query: { type: 'string' },
        limit: { type: 'number' }
      },
      required: ['query']
    }
  },
  {
    name: 'ask',
    description: 'Ask questions about your memories. AI answers if intelligence model is available.',
    inputSchema: {
      type: 'object',
      properties: {
        question: { type: 'string' },
        context_limit: { type: 'number' }
      },
      required: ['question']
    }
  },
  {
    name: 'summarize',
    description: 'Summarize memories on a topic. AI summary if intelligence model is available.',
    inputSchema: {
      type: 'object',
      properties: {
        query: { type: 'string' },
        keys: { type: 'array', items: { type: 'string' } },
        style: { type: 'string', enum: ['concise', 'detailed', 'beginner'] }
      }
    }
  },
  {
    name: 'get_provider_info',
    description: 'Get information about the configured AI provider',
    inputSchema: { type: 'object' }
  }
];

// Tool handlers
const tools = {
  store_memory: async (args) => {
    const { key, content, tags = [], auto_tag = true } = args;
    const result = await engine.storeMemory(key, content, { tags, autoTag: auto_tag, source: 'mcp' });
    const aiEnhanced = result.tags.length > tags.length;
    return {
      content: [{
        type: 'text',
        text: `✅ Stored: **${result.memory.id}**\n\n🏷️ Tags: ${result.tags.join(', ') || 'none'} ${aiEnhanced ? '(AI-enhanced)' : ''}\n📦 Chunks: ${result.chunks}`
      }]
    };
  },

  get_memory: async (args) => {
    const memory = await engine.recallMemory(args.key);
    if (!memory) {
      return { content: [{ type: 'text', text: `❌ Memory not found: **${args.key}**` }] };
    }
    return {
      content: [{
        type: 'text',
        text: `## ${memory.id}\n\n${memory.content}\n\n---\n🏷️ Tags: ${memory.tags?.join(', ') || 'none'}\n📊 Importance: ${memory.importance}`
      }]
    };
  },

  update_memory: async (args) => {
    const { key, content, tags, merge_tags = false } = args;
    const existing = await engine.recallMemory(key);
    if (!existing) {
      return { content: [{ type: 'text', text: `❌ Memory not found: **${key}**` }] };
    }
    const finalTags = merge_tags && tags ? [...new Set([...existing.tags, ...tags])] : tags || existing.tags;
    const result = await engine.storeMemory(key, content || existing.content, { tags: finalTags });
    return { content: [{ type: 'text', text: `✅ Updated: **${key}**\n\n🏷️ Tags: ${result.tags.join(', ')}` }] };
  },

  delete_memory: async (args) => {
    const result = await engine.deleteMemory(args.key);
    return {
      content: [{ type: 'text', text: result.deleted ? `✅ Deleted: **${args.key}**` : `❌ ${result.error}` }]
    };
  },

  search: async (args) => {
    const { query, limit = 10 } = args;
    const results = await engine.searchMemories(query, { topK: limit, mode: 'hybrid' });
    if (results.length === 0) {
      return { content: [{ type: 'text', text: `🔍 No results for: "${query}"` }] };
    }
    const formatted = results.map((r, i) =>
      `${i + 1}. **${r.memory.id}** [${(r.score * 100).toFixed(0)}%]\n   ${r.memory.content.substring(0, 120).replace(/\n/g, ' ')}...`
    ).join('\n\n');
    return { content: [{ type: 'text', text: `**${results.length} results** for "${query}":\n\n${formatted}` }] };
  },

  list_memories: async (args) => {
    const { filter, limit = 50 } = args;
    const memories = engine.listMemories({ filter, limit, sortBy: 'createdAt' });
    const formatted = memories.map(m => `• **${m.id}** (${m.tags?.slice(0, 3).join(', ') || 'no tags'})`).join('\n');
    return { content: [{ type: 'text', text: `**${memories.length} memories**:\n\n${formatted}` }] };
  },

  query_graph: async (args) => {
    const { concept, depth = 1, find_path_to } = args;
    if (concept && find_path_to) {
      const path = engine.knowledgeGraph.findPath(concept, find_path_to);
      return {
        content: [{ type: 'text', text: path ? `**Path:** ${path.join(' → ')}` : `No path found` }]
      };
    }
    if (concept) {
      const related = engine.knowledgeGraph.getRelatedConcepts(concept, depth);
      const memories = engine.knowledgeGraph.getMemoriesForConcept(concept);
      const formatted = related.slice(1).map(r => `• ${r.concept} (${(r.strength * 100).toFixed(0)}%)`).join('\n');
      return {
        content: [{
          type: 'text',
          text: `**"${concept}"** - ${related.length - 1} connections, ${memories.length} memories:\n\n${formatted || 'No connections'}`
        }]
      };
    }
    const stats = engine.knowledgeGraph.getStats();
    const top = engine.knowledgeGraph.getTopConcepts(10);
    return {
      content: [{
        type: 'text',
        text: `**Knowledge Graph:** ${stats.concepts} concepts, ${stats.relationships} relationships\n\n**Top:**\n${top.map(c => `• ${c.name}`).join('\n')}`
      }]
    };
  },

  get_stats: async () => {
    const stats = engine.getStats();
    return {
      content: [{
        type: 'text',
        text: `**System Stats**\n\n📚 Memories: ${stats.totalMemories}\n📦 Chunks: ${stats.totalChunks}\n🧠 Embeddings: ${stats.totalEmbeddings}\n🕸️ Concepts: ${stats.totalConcepts}\n🤖 Intelligence: ${stats.intelligenceEnabled ? 'ON' : 'OFF'}`
      }]
    };
  },

  backup: async () => {
    const snapshotPath = await engine.createSnapshot();
    return { content: [{ type: 'text', text: `✅ Backup: \`${snapshotPath}\`` }] };
  },

  smart_search: async (args) => {
    return tools.search(args);
  },

  ask: async (args) => {
    const { question, context_limit = 3 } = args;
    const relevant = await engine.searchMemories(question, { topK: context_limit, mode: 'hybrid' });
    if (relevant.length === 0) {
      return { content: [{ type: 'text', text: `No relevant memories for: "${question}"` }] };
    }
    const hasAI = intelligenceProvider?.isAvailable?.();
    if (!hasAI) {
      const snippets = relevant.map((r, i) => `**${i + 1}. ${r.memory.id}**\n${r.memory.content.substring(0, 300)}...`).join('\n\n---\n\n');
      return { content: [{ type: 'text', text: `**Relevant memories:**\n\n${snippets}` }] };
    }
    const context = relevant.map(r => r.memory.content).join('\n\n---\n\n');
    const answer = await intelligenceProvider.synthesize(context, `Answer: ${question}`, 'detailed');
    return {
      content: [{
        type: 'text',
        text: `**Q: ${question}**\n\n${answer}\n\n---\n*Sources: ${relevant.map(r => r.memory.id).join(', ')}*`
      }]
    };
  },

  summarize: async (args) => {
    const { query, keys = [], style = 'concise' } = args;
    const hasAI = intelligenceProvider?.isAvailable?.();
    let memories = [];
    if (keys.length > 0) {
      memories = (await Promise.all(keys.map(k => engine.recallMemory(k)))).filter(m => m);
    } else if (query) {
      memories = (await engine.searchMemories(query, { topK: 5, mode: 'hybrid' })).map(r => r.memory);
    }
    if (memories.length === 0) {
      return { content: [{ type: 'text', text: 'No memories to summarize' }] };
    }
    if (!hasAI) {
      const concepts = new Set();
      memories.forEach(m => { m.concepts?.forEach(c => concepts.add(c)); m.tags?.forEach(t => concepts.add(t)); });
      return {
        content: [{
          type: 'text',
          text: `**Key Concepts:** ${Array.from(concepts).slice(0, 10).join(', ')}\n\n**Memories:** ${memories.map(m => `• ${m.id}`).join('\n')}`
        }]
      };
    }
    const content = memories.map(m => m.content).join('\n\n---\n\n');
    const summary = await intelligenceProvider.synthesize(content, `Summarize in ${style} style`, style);
    return { content: [{ type: 'text', text: `**Summary:**\n\n${summary}` }] };
  },

  get_provider_info: async () => {
    const embConfig = embeddingProvider.getConfig?.() || { type: PROVIDER_TYPE };
    const intConfig = intelligenceProvider.getConfig?.() || { type: INTELLIGENCE_PROVIDER || PROVIDER_TYPE };
    
    return {
      content: [{
        type: 'text',
        text: `**AI Provider Configuration**\n\n` +
              `🧠 Embeddings: ${embConfig.type}\n` +
              `   Model: ${embConfig.embeddingModel || EMBEDDING_MODEL}\n` +
              `   Available: ${embeddingProvider.isAvailable() ? '✅' : '❌'}\n\n` +
              `🤖 Intelligence: ${intConfig.type}\n` +
              `   Model: ${intConfig.model || intConfig.chatModel || CHAT_MODEL}\n` +
              `   Available: ${intelligenceProvider.isAvailable() ? '✅' : '❌'}`
      }]
    };
  }
};

// Function to setup server handlers
function setupServerHandlers(server) {
  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: toolDefinitions
  }));

  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params;
    if (!tools[name]) {
      throw new McpError(ErrorCode.InvalidParams, `Unknown tool: ${name}`);
    }
    return await tools[name](args || {});
  });
}

// Create reusable MCP server instance
function createMcpServer() {
  const server = new Server(
    { name: 'adaptive-memory-engine', version: '1.0.0' },
    { capabilities: { tools: {} } }
  );
  setupServerHandlers(server);
  return server;
}

// ==================== TRANSPORT SETUP ====================

// Restore console.log for HTTP mode (Express server can use stdout)
if (TRANSPORT === 'http') {
  console.log = originalLog;
  const app = express();
  app.use(express.json({ limit: '50mb' }));

  // Map to store transports by session ID
  const transports = {};

  // POST handler: JSON-RPC messages (tool calls, initialization, etc.)
  app.post('/mcp', async (req, res) => {
    try {
      const sessionId = req.headers['mcp-session-id'];
      let transport;

      if (sessionId && transports[sessionId]) {
        // Reuse existing transport for this session
        transport = transports[sessionId];
      } else if (!sessionId && isInitializeRequest(req.body)) {
        // New initialization request - create a new transport
        transport = new StreamableHTTPServerTransport({
          sessionIdGenerator: () => randomUUID(),
          onsessioninitialized: (sid) => {
            console.error(`[Session] Initialized: ${sid}`);
            transports[sid] = transport;
          }
        });

        // Clean up transport when closed
        transport.onclose = () => {
          const sid = transport.sessionId;
          if (sid && transports[sid]) {
            console.error(`[Session] Closed: ${sid}`);
            delete transports[sid];
          }
        };

        // Connect the transport to the MCP server
        const server = createMcpServer();
        await server.connect(transport);
        await transport.handleRequest(req, res, req.body);
        return;
      } else {
        // Invalid request - no session ID or not initialization request
        res.status(400).json({
          jsonrpc: '2.0',
          error: {
            code: -32000,
            message: 'Bad Request: No valid session ID provided'
          },
          id: null
        });
        return;
      }

      // Handle request with existing transport
      await transport.handleRequest(req, res, req.body);
    } catch (error) {
      console.error('[HTTP] POST /mcp error:', error);
      if (!res.headersSent) {
        res.status(500).json({
          jsonrpc: '2.0',
          error: {
            code: -32603,
            message: 'Internal server error'
          },
          id: null
        });
      }
    }
  });

  // GET handler: SSE stream for streaming responses
  app.get('/mcp', async (req, res) => {
    try {
      const sessionId = req.headers['mcp-session-id'];
      if (!sessionId || !transports[sessionId]) {
        res.status(400).send('Invalid or missing session ID');
        return;
      }

      const transport = transports[sessionId];
      await transport.handleRequest(req, res);
    } catch (error) {
      console.error('[HTTP] GET /mcp error:', error);
      if (!res.headersSent) {
        res.status(500).send('Error establishing SSE stream');
      }
    }
  });

  // DELETE handler: Session termination
  app.delete('/mcp', async (req, res) => {
    try {
      const sessionId = req.headers['mcp-session-id'];
      if (!sessionId || !transports[sessionId]) {
        res.status(400).send('Invalid or missing session ID');
        return;
      }

      console.error(`[Session] Termination request: ${sessionId}`);
      const transport = transports[sessionId];
      await transport.handleRequest(req, res);
    } catch (error) {
      console.error('[HTTP] DELETE /mcp error:', error);
      if (!res.headersSent) {
        res.status(500).send('Error processing session termination');
      }
    }
  });

  // Health endpoint
  app.get('/health', (req, res) => {
    const s = engine.getStats();
    res.json({ 
      status: 'ok', 
      memories: s.totalMemories, 
      concepts: s.totalConcepts, 
      embeddings: s.totalEmbeddings,
      provider: PROVIDER_TYPE
    });
  });

  app.listen(PORT, '0.0.0.0', () => {
    console.log(`[AdaptiveMemoryEngine] Streamable HTTP server listening on port ${PORT}`);
    console.log(`  MCP endpoint:  POST http://localhost:${PORT}/mcp`);
    console.log(`  SSE stream:    GET  http://localhost:${PORT}/mcp`);
    console.log(`  Session end:   DELETE http://localhost:${PORT}/mcp`);
    console.log(`  Health:        GET  http://localhost:${PORT}/health`);
  });

  process.on('SIGINT', async () => {
    console.log('[AdaptiveMemoryEngine] Shutting down...');
    for (const sessionId in transports) {
      try {
        await transports[sessionId].close();
        delete transports[sessionId];
      } catch (e) {
        // Ignore close errors during shutdown
      }
    }
    process.exit(0);
  });
} else {
  // Stdio mode (default)
  const server = createMcpServer();
  
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error('[AdaptiveMemoryEngine] Connected via stdio');
}