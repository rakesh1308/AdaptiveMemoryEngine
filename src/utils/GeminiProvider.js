/**
 * GeminiProvider - Google Gemini API provider
 * 
 * Features:
 * - Fast embeddings (text-embedding-004)
 * - Strong multilingual support
 * - Generous free tier
 * 
 * Environment:
 *   GEMINI_API_KEY=your_api_key
 *   GEMINI_EMBEDDING_MODEL=text-embedding-004
 *   GEMINI_CHAT_MODEL=gemini-1.5-flash
 * 
 * Get API key: https://aistudio.google.com/app/apikey
 */

import { IntelligentProvider } from '../interfaces/EmbeddingProvider.js';

export class GeminiProvider extends IntelligentProvider {
  constructor(options = {}) {
    super({
      name: 'Gemini',
      dimensions: options.dimensions || 768,
      ...options
    });
    
    this.apiKey = options.apiKey || process.env.GEMINI_API_KEY;
    this.embeddingModel = options.embeddingModel || process.env.GEMINI_EMBEDDING_MODEL || 'text-embedding-004';
    this.chatModel = options.chatModel || process.env.GEMINI_CHAT_MODEL || 'gemini-1.5-flash';
    this.baseUrl = 'https://generativelanguage.googleapis.com/v1beta';
  }

  isAvailable() {
    return !!this.apiKey;
  }

  async embed(text) {
    if (!this.apiKey) return null;

    try {
      const response = await fetch(
        `${this.baseUrl}/models/${this.embeddingModel}:embedContent?key=${this.apiKey}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            model: `models/${this.embeddingModel}`,
            content: {
              parts: [{ text: text.substring(0, 10000) }]
            }
          })
        }
      );

      if (!response.ok) {
        const error = await response.text();
        throw new Error(`Gemini embedding error: ${error}`);
      }

      const data = await response.json();
      return data.embedding?.values || null;
    } catch (err) {
      console.error(`[GeminiProvider] Embedding failed: ${err.message}`);
      return null;
    }
  }

  async embedBatch(texts) {
    if (!this.apiKey || texts.length === 0) {
      return texts.map(() => null);
    }

    try {
      const response = await fetch(
        `${this.baseUrl}/models/${this.embeddingModel}:batchEmbedContents?key=${this.apiKey}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            requests: texts.map(text => ({
              model: `models/${this.embeddingModel}`,
              content: {
                parts: [{ text: text.substring(0, 10000) }]
              }
            }))
          })
        }
      );

      if (!response.ok) {
        const error = await response.text();
        throw new Error(`Gemini batch embedding error: ${error}`);
      }

      const data = await response.json();
      return data.embeddings?.map(e => e.values) || texts.map(() => null);
    } catch (err) {
      console.error(`[GeminiProvider] Batch embedding failed: ${err.message}`);
      // Fallback to individual calls
      return Promise.all(texts.map(t => this.embed(t)));
    }
  }

  async autoTag(key, content) {
    if (!this.apiKey) return [];

    const prompt = `Generate 5-10 relevant tags for this content.
Return ONLY a JSON array of lowercase, hyphenated tags.

Title: ${key}
Content: ${content.substring(0, 2000)}`;

    try {
      const result = await this.generateContent(prompt);
      const cleaned = result
        .replace(/```json/g, '')
        .replace(/```/g, '')
        .trim();
      return JSON.parse(cleaned);
    } catch (err) {
      console.error(`[GeminiProvider] Auto-tag failed: ${err.message}`);
      return [];
    }
  }

  async synthesize(content, task, style = '') {
    if (!this.apiKey) {
      return content.substring(0, 1500);
    }

    const styleGuides = {
      beginner: 'Explain simply for beginners.',
      detailed: 'Be comprehensive with examples.',
      concise: 'Be extremely brief.'
    };

    const prompt = `${styleGuides[style] || ''}

Context:
${content.substring(0, 7000)}

Task: ${task}`;

    try {
      return await this.generateContent(prompt);
    } catch (err) {
      console.error(`[GeminiProvider] Synthesis failed: ${err.message}`);
      return content.substring(0, 1500);
    }
  }

  async extractGraphEntities(content) {
    if (!this.apiKey) return { concepts: [], relationships: [] };

    const prompt = `Extract key concepts and relationships from this text.
Return ONLY JSON in this exact format:
{
  "concepts": ["concept1", "concept2"],
  "relationships": [{"from": "c1", "to": "c2", "type": "related_to", "strength": 0.8}]
}

Text: ${content.substring(0, 3000)}`;

    try {
      const result = await this.generateContent(prompt);
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
      console.error(`[GeminiProvider] Graph extraction failed: ${err.message}`);
      return { concepts: [], relationships: [] };
    }
  }

  async generateContent(prompt) {
    const response = await fetch(
      `${this.baseUrl}/models/${this.chatModel}:generateContent?key=${this.apiKey}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          contents: [{
            parts: [{ text: prompt }]
          }],
          generationConfig: {
            temperature: 0.2,
            maxOutputTokens: 2048
          }
        })
      }
    );

    if (!response.ok) {
      throw new Error(await response.text());
    }

    const data = await response.json();
    return data.candidates?.[0]?.content?.parts?.[0]?.text || '';
  }

  getConfig() {
    return {
      type: 'gemini',
      embeddingModel: this.embeddingModel,
      chatModel: this.chatModel,
      dimensions: this.dimensions,
      hasApiKey: !!this.apiKey
    };
  }
}
