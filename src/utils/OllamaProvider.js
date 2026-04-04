/**
 * OllamaProvider - Local AI/embedding provider using Ollama
 * 
 * Perfect for:
 * - Privacy-conscious users (data stays local)
 * - Offline usage
 * - Cost savings (no API fees)
 * 
 * Setup:
 *   1. Install Ollama: https://ollama.com
 *   2. Pull models: `ollama pull nomic-embed-text` and `ollama pull llama3.2`
 *   3. Set OLLAMA_HOST if not running on localhost
 * 
 * Environment:
 *   OLLAMA_HOST=http://localhost:11434
 *   OLLAMA_EMBEDDING_MODEL=nomic-embed-text
 *   OLLAMA_CHAT_MODEL=llama3.2
 */

import { IntelligentProvider } from '../interfaces/EmbeddingProvider.js';

export class OllamaProvider extends IntelligentProvider {
  constructor(options = {}) {
    super({
      name: 'Ollama',
      dimensions: options.dimensions || 768, // nomic-embed-text is 768d
      ...options
    });
    
    this.baseUrl = options.baseUrl || process.env.OLLAMA_HOST || 'http://localhost:11434';
    this.embeddingModel = options.embeddingModel || process.env.OLLAMA_EMBEDDING_MODEL || 'nomic-embed-text';
    this.chatModel = options.chatModel || process.env.OLLAMA_CHAT_MODEL || 'llama3.2';
  }

  isAvailable() {
    // Ollama is available if we can reach the server
    return this.checkConnection().catch(() => false);
  }

  async checkConnection() {
    try {
      const response = await fetch(`${this.baseUrl}/api/tags`, { 
        method: 'GET',
        signal: AbortSignal.timeout(5000)
      });
      return response.ok;
    } catch {
      return false;
    }
  }

  async embed(text) {
    try {
      const response = await fetch(`${this.baseUrl}/api/embeddings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: this.embeddingModel,
          prompt: text
        })
      });

      if (!response.ok) {
        const error = await response.text();
        throw new Error(`Ollama embedding error: ${error}`);
      }

      const data = await response.json();
      return data.embedding;
    } catch (err) {
      console.error(`[OllamaProvider] Embedding failed: ${err.message}`);
      return null;
    }
  }

  async embedBatch(texts) {
    // Ollama doesn't support batch embedding, so we do sequential
    const results = [];
    for (const text of texts) {
      const embedding = await this.embed(text);
      results.push(embedding);
      // Small delay to avoid overwhelming local server
      await new Promise(r => setTimeout(r, 10));
    }
    return results;
  }

  async autoTag(key, content) {
    try {
      const prompt = `Generate 5-10 relevant tags for this content.
Title: ${key}
Content: ${content.substring(0, 2000)}

Return ONLY a JSON array of lowercase, hyphenated tags.
Example: ["machine-learning", "python", "tutorial"]`;

      const response = await fetch(`${this.baseUrl}/api/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: this.chatModel,
          prompt,
          stream: false,
          format: 'json'
        })
      });

      if (!response.ok) return [];

      const data = await response.json();
      const parsed = JSON.parse(data.response);
      return Array.isArray(parsed) ? parsed : parsed.tags || [];
    } catch (err) {
      console.error(`[OllamaProvider] Auto-tag failed: ${err.message}`);
      return [];
    }
  }

  async synthesize(content, task, style = '') {
    const styleGuides = {
      beginner: 'Use simple language. Explain like I\'m 5.',
      detailed: 'Be thorough with examples.',
      concise: 'Be brief. Maximum 3 sentences.'
    };

    const prompt = `${styleGuides[style] || ''}

Context from notes:
${content.substring(0, 4000)}

Task: ${task}

Provide a helpful response based on the context.`;

    try {
      const response = await fetch(`${this.baseUrl}/api/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: this.chatModel,
          prompt,
          stream: false
        })
      });

      if (!response.ok) {
        throw new Error(await response.text());
      }

      const data = await response.json();
      return data.response.trim();
    } catch (err) {
      console.error(`[OllamaProvider] Synthesis failed: ${err.message}`);
      return content.substring(0, 1500);
    }
  }

  async extractGraphEntities(content) {
    const prompt = `Extract key concepts and relationships from this text as JSON.

Text: ${content.substring(0, 3000)}

Return format:
{
  "concepts": ["concept1", "concept2", ...],
  "relationships": [
    {"from": "concept1", "to": "concept2", "type": "related_to", "strength": 0.8}
  ]
}`;

    try {
      const response = await fetch(`${this.baseUrl}/api/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: this.chatModel,
          prompt,
          stream: false,
          format: 'json'
        })
      });

      if (!response.ok) return { concepts: [], relationships: [] };

      const data = await response.json();
      const parsed = JSON.parse(data.response);
      return {
        concepts: Array.isArray(parsed.concepts) ? parsed.concepts : [],
        relationships: Array.isArray(parsed.relationships) ? parsed.relationships : []
      };
    } catch (err) {
      console.error(`[OllamaProvider] Graph extraction failed: ${err.message}`);
      return { concepts: [], relationships: [] };
    }
  }

  getConfig() {
    return {
      type: 'ollama',
      baseUrl: this.baseUrl,
      embeddingModel: this.embeddingModel,
      chatModel: this.chatModel,
      dimensions: this.dimensions
    };
  }
}
