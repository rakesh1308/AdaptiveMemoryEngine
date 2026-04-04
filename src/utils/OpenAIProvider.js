/**
 * OpenAIProvider - Embedding and AI service provider
 * 
 * Capabilities:
 * - Embeddings (required): text-embedding-3-small or similar
 * - Intelligence (optional): auto-tagging, synthesis, query expansion, graph extraction
 */

export class OpenAIProvider {
  constructor(options = {}) {
    this.apiKey = options.apiKey || process.env.OPENAI_API_KEY;
    this.embeddingModel = options.embeddingModel || process.env.OPENAI_EMBEDDING_MODEL || 'text-embedding-3-small';
    this.chatModel = options.chatModel || process.env.OPENAI_CHAT_MODEL || 'gpt-4o-mini';
    this.baseUrl = options.baseUrl || 'https://api.openai.com/v1';
    this.batchSize = options.batchSize || 20;
    
    if (!this.apiKey) {
      console.warn('[OpenAIProvider] No API key provided - provider unavailable');
    }
  }

  isAvailable() {
    return !!this.apiKey;
  }

  async embed(text) {
    if (!this.apiKey) return null;
    
    const response = await fetch(`${this.baseUrl}/embeddings`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${this.apiKey}`
      },
      body: JSON.stringify({
        model: this.embeddingModel,
        input: this.cleanText(text)
      })
    });
    
    if (!response.ok) {
      const error = await response.text();
      throw new Error(`Embedding error: ${error}`);
    }
    
    const data = await response.json();
    return data.data[0].embedding;
  }

  async embedBatch(texts) {
    if (!this.apiKey || texts.length === 0) {
      return texts.map(() => null);
    }
    
    const results = [];
    
    for (let i = 0; i < texts.length; i += this.batchSize) {
      const batch = texts.slice(i, i + this.batchSize).map(t => this.cleanText(t));
      
      try {
        const response = await fetch(`${this.baseUrl}/embeddings`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${this.apiKey}`
          },
          body: JSON.stringify({
            model: this.embeddingModel,
            input: batch
          })
        });
        
        if (!response.ok) {
          console.error(`[OpenAIProvider] Batch embedding error: ${await response.text()}`);
          batch.forEach(() => results.push(null));
          continue;
        }
        
        const data = await response.json();
        data.data
          .sort((a, b) => a.index - b.index)
          .forEach(d => results.push(d.embedding));
          
      } catch (err) {
        console.error(`[OpenAIProvider] Batch error: ${err.message}`);
        batch.forEach(() => results.push(null));
      }
    }
    
    return results;
  }

  async autoTag(key, content) {
    if (!this.apiKey) return [];
    
    try {
      const response = await fetch(`${this.baseUrl}/chat/completions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${this.apiKey}`
        },
        body: JSON.stringify({
          model: this.chatModel,
          max_tokens: 150,
          temperature: 0,
          messages: [
            {
              role: 'system',
              content: `You are a tagging assistant. Given a document title and content, generate 8-15 relevant tags.
Return ONLY a JSON array of lowercase kebab-case tags.
Include: topic areas, technologies, concepts, and document type.
Example: ["javascript", "async-programming", "tutorial", "nodejs", "promises"]`
            },
            {
              role: 'user',
              content: `Title: ${key}\n\nContent (first 1500 chars):\n${content.substring(0, 1500)}`
            }
          ]
        })
      });
      
      if (!response.ok) {
        console.error(`[OpenAIProvider] Auto-tag error: ${await response.text()}`);
        return [];
      }
      
      const data = await response.json();
      const raw = data.choices[0].message.content.trim();
      const cleaned = raw
        .replace(/```(?:json)?/g, '')
        .replace(/```/g, '')
        .trim();
      
      return JSON.parse(cleaned);
      
    } catch (err) {
      console.error(`[OpenAIProvider] Auto-tag parse error: ${err.message}`);
      return [];
    }
  }

  async synthesize(content, task, style = '') {
    if (!this.apiKey) {
      return `## Raw Content\n\n${content.substring(0, 2000)}\n\n*(AI synthesis disabled - no API key)*`;
    }
    
    const styleGuides = {
      beginner: 'Use simple language and real-world analogies. Assume zero prior knowledge.',
      advanced: 'Be concise and technical. Focus on edge cases and implementation details.',
      visual: 'Use ASCII diagrams and step-by-step traces where helpful.',
      concise: 'Be extremely brief — max 150 words.',
      detailed: 'Be comprehensive and thorough. Include examples and edge cases.'
    };
    
    const styleGuide = styleGuides[style] || '';
    
    try {
      const response = await fetch(`${this.baseUrl}/chat/completions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${this.apiKey}`
        },
        body: JSON.stringify({
          model: this.chatModel,
          max_tokens: 1500,
          temperature: 0.4,
          messages: [
            {
              role: 'system',
              content: `You are a helpful AI assistant working from personal notes. ${styleGuide}
Respond in the format most appropriate for the task. Be direct and practical.
Cite your sources when possible.`
            },
            {
              role: 'user',
              content: `Task: ${task}\n\nRelevant content from notes:\n\n${content.substring(0, 7000)}`
            }
          ]
        })
      });
      
      if (!response.ok) {
        throw new Error(await response.text());
      }
      
      const data = await response.json();
      return data.choices[0].message.content.trim();
      
    } catch (err) {
      console.error(`[OpenAIProvider] Synthesis error: ${err.message}`);
      return `${content.substring(0, 1500)}\n\n*(AI synthesis failed - raw notes shown)*`;
    }
  }

  async expandQuery(query) {
    if (!this.apiKey) return [query];
    
    try {
      const response = await fetch(`${this.baseUrl}/chat/completions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${this.apiKey}`
        },
        body: JSON.stringify({
          model: this.chatModel,
          max_tokens: 150,
          temperature: 0,
          messages: [
            {
              role: 'system',
              content: `Given a search query, generate 10-15 related search terms.
Include: sub-topics, related concepts, prerequisites, and common aliases.
Return ONLY a JSON array of strings.`
            },
            {
              role: 'user',
              content: `Query: "${query}"`
            }
          ]
        })
      });
      
      if (!response.ok) return [query];
      
      const data = await response.json();
      const raw = data.choices[0].message.content.trim()
        .replace(/```[a-z]*/g, '')
        .replace(/```/g, '')
        .trim();
      
      const terms = JSON.parse(raw);
      return Array.isArray(terms) && terms.length > 0 ? terms : [query];
      
    } catch (err) {
      console.error(`[OpenAIProvider] Query expansion error: ${err.message}`);
      return [query];
    }
  }

  /**
   * Extract concepts and relationships for the knowledge graph
   * Returns: { concepts: string[], relationships: [{from, to, type, strength}] }
   */
  async extractGraphEntities(content) {
    if (!this.apiKey) {
      return { concepts: [], relationships: [] };
    }
    
    try {
      const response = await fetch(`${this.baseUrl}/chat/completions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${this.apiKey}`
        },
        body: JSON.stringify({
          model: this.chatModel,
          max_tokens: 800,
          temperature: 0,
          messages: [
            {
              role: 'system',
              content: `You are a knowledge graph extractor. Given content, extract key concepts and their relationships.
Return ONLY a JSON object in this exact format:
{
  "concepts": ["concept1", "concept2", ...],
  "relationships": [
    {"from": "concept1", "to": "concept2", "type": "related_to", "strength": 0.8}
  ]
}
Rules:
- Extract 5-15 meaningful concepts (technologies, ideas, entities, domains)
- Relationships should be meaningful (not every concept connected to every other)
- Use relationship types like: related_to, implements, part_of, prerequisite_for, uses, built_with
- Strength is 0.0 to 1.0`
            },
            {
              role: 'user',
              content: `Extract concepts and relationships from:\n\n${content.substring(0, 3000)}`
            }
          ]
        })
      });
      
      if (!response.ok) {
        console.error(`[OpenAIProvider] Graph extraction error: ${await response.text()}`);
        return { concepts: [], relationships: [] };
      }
      
      const data = await response.json();
      const raw = data.choices[0].message.content.trim()
        .replace(/```(?:json)?/g, '')
        .replace(/```/g, '')
        .trim();
      
      const parsed = JSON.parse(raw);
      return {
        concepts: Array.isArray(parsed.concepts) ? parsed.concepts : [],
        relationships: Array.isArray(parsed.relationships) ? parsed.relationships : []
      };
      
    } catch (err) {
      console.error(`[OpenAIProvider] Graph extraction parse error: ${err.message}`);
      return { concepts: [], relationships: [] };
    }
  }

  cleanText(text) {
    return text
      .substring(0, 8000)
      .replace(/\n+/g, ' ')
      .trim();
  }
}
