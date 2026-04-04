/**
 * AnthropicProvider - Claude API provider for intelligence features
 * 
 * Note: Anthropic doesn't provide embeddings (yet), so this provider
 * is for intelligence features only (auto-tag, synthesis, etc).
 * 
 * Pair with another provider for embeddings:
 *   - Use OpenAI/Ollama/Gemini for embeddings
 *   - Use Anthropic for intelligence
 * 
 * Environment:
 *   ANTHROPIC_API_KEY=your_api_key
 *   ANTHROPIC_MODEL=claude-3-haiku-20240307
 * 
 * Get API key: https://console.anthropic.com
 */

import { IntelligentProvider } from '../interfaces/EmbeddingProvider.js';

export class AnthropicProvider extends IntelligentProvider {
  constructor(options = {}) {
    super({
      name: 'Anthropic',
      dimensions: options.dimensions || 1536,
      ...options
    });
    
    this.apiKey = options.apiKey || process.env.ANTHROPIC_API_KEY;
    this.model = options.chatModel || process.env.ANTHROPIC_MODEL || 'claude-3-haiku-20240307';
    this.baseUrl = options.baseUrl || 'https://api.anthropic.com/v1';
    
    // For embeddings, we need a fallback provider
    this.embeddingFallback = options.embeddingFallback;
  }

  isAvailable() {
    return !!this.apiKey;
  }

  /**
   * Anthropic doesn't provide embeddings API yet.
   * This will use the fallback provider or return null.
   */
  async embed(text) {
    if (this.embeddingFallback) {
      return this.embeddingFallback.embed(text);
    }
    
    console.error(
      '[AnthropicProvider] Embeddings not supported. ' +
      'Use a different provider for embeddings or set embeddingFallback.'
    );
    return null;
  }

  async embedBatch(texts) {
    if (this.embeddingFallback) {
      return this.embeddingFallback.embedBatch(texts);
    }
    return texts.map(() => null);
  }

  async autoTag(key, content) {
    if (!this.apiKey) return [];

    const prompt = `Generate 5-10 relevant tags for this content.
Return ONLY a JSON array of lowercase, hyphenated tags like ["tag-one", "tag-two"].

Title: ${key}
Content: ${content.substring(0, 3000)}`;

    try {
      const result = await this.createMessage(prompt);
      const cleaned = result
        .replace(/```json/g, '')
        .replace(/```/g, '')
        .trim();
      return JSON.parse(cleaned);
    } catch (err) {
      console.error(`[AnthropicProvider] Auto-tag failed: ${err.message}`);
      return [];
    }
  }

  async synthesize(content, task, style = '') {
    if (!this.apiKey) {
      return content.substring(0, 1500);
    }

    const styleGuides = {
      beginner: 'Explain simply for beginners using analogies.',
      detailed: 'Be comprehensive with examples and edge cases.',
      concise: 'Be extremely brief. One paragraph maximum.'
    };

    const system = `You are a helpful assistant. ${styleGuides[style] || ''}`;
    const prompt = `Context from notes:\n${content.substring(0, 8000)}\n\nTask: ${task}`;

    try {
      return await this.createMessage(prompt, system);
    } catch (err) {
      console.error(`[AnthropicProvider] Synthesis failed: ${err.message}`);
      return content.substring(0, 1500);
    }
  }

  async extractGraphEntities(content) {
    if (!this.apiKey) return { concepts: [], relationships: [] };

    const system = 'You extract knowledge graph data. Return ONLY valid JSON.';
    const prompt = `Extract key concepts and relationships from this text.
Return JSON format:
{
  "concepts": ["concept1", "concept2", ...],
  "relationships": [
    {"from": "concept1", "to": "concept2", "type": "related_to", "strength": 0.8}
  ]
}

Text: ${content.substring(0, 4000)}`;

    try {
      const result = await this.createMessage(prompt, system);
      const cleaned = result
        .replace(/```json/g, '')
        .replace(/```/g, '')
        .trim();
      const parsed = JSON.parse(cleaned);
      return {
        concepts: Array.isArray(parsed.concepts) ? parsed.concepts : [],
        relationships: Array.isArray(parsed.relationships) ? parsed.relationships : []
      };
    } catch (err) {
      console.error(`[AnthropicProvider] Graph extraction failed: ${err.message}`);
      return { concepts: [], relationships: [] };
    }
  }

  async createMessage(prompt, system = '') {
    const body = {
      model: this.model,
      max_tokens: 2048,
      messages: [{ role: 'user', content: prompt }]
    };

    if (system) {
      body.system = system;
    }

    const response = await fetch(`${this.baseUrl}/messages`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': this.apiKey,
        'anthropic-version': '2023-06-01'
      },
      body: JSON.stringify(body)
    });

    if (!response.ok) {
      throw new Error(await response.text());
    }

    const data = await response.json();
    return data.content?.[0]?.text || '';
  }

  getConfig() {
    return {
      type: 'anthropic',
      model: this.model,
      dimensions: this.dimensions,
      hasApiKey: !!this.apiKey,
      hasEmbeddingFallback: !!this.embeddingFallback,
      note: 'Requires embeddingFallback for embeddings'
    };
  }
}
