/**
 * KnowledgeGraph - Manages conceptual relationships between memories
 * 
 * Modes:
 * - Regex-based extraction (always works)
 * - AI-enhanced extraction (when intelligenceProvider is available)
 */

import fs from 'fs';
import { EventBus, MemoryEvents } from '../infrastructure/EventBus.js';

export class KnowledgeGraph {
  constructor(options = {}) {
    this.concepts = new Map();
    this.relationships = new Map();
    this.conceptIndex = new Map();
    this.eventBus = options.eventBus || new EventBus();
    this.minConfidence = options.minConfidence || 0.3;
    this.dataDir = options.dataDir || './data';
    this.graphFile = `${this.dataDir}/knowledge-graph.json`;
    this.dirty = false;
    this.intelligenceProvider = options.intelligenceProvider || null;
    
    this.startAutoSave();
  }

  startAutoSave() {
    setInterval(() => {
      if (this.dirty) {
        this.save().catch(err => console.error('[KnowledgeGraph] Auto-save failed:', err.message));
      }
    }, 30000);
  }

  async save() {
    try {
      if (!fs.existsSync(this.dataDir)) {
        fs.mkdirSync(this.dataDir, { recursive: true });
      }
      
      const data = {
        concepts: Array.from(this.concepts.entries()).map(([id, node]) => [
          id,
          {
            ...node,
            memoryIds: Array.from(node.memoryIds),
            relatedConcepts: Array.from(node.relatedConcepts.entries())
          }
        ]),
        relationships: Array.from(this.relationships.entries()),
        conceptIndex: Array.from(this.conceptIndex.entries()).map(([id, set]) => [id, Array.from(set)]),
        savedAt: new Date().toISOString()
      };
      
      fs.writeFileSync(this.graphFile, JSON.stringify(data, null, 2));
      this.dirty = false;
      console.log(`[KnowledgeGraph] Saved ${this.concepts.size} concepts, ${this.relationships.size} relationships`);
    } catch (err) {
      console.error('[KnowledgeGraph] Save failed:', err.message);
    }
  }

  async load() {
    try {
      if (!fs.existsSync(this.graphFile)) {
        console.log('[KnowledgeGraph] No saved graph found, starting fresh');
        return false;
      }
      
      const data = JSON.parse(fs.readFileSync(this.graphFile, 'utf-8'));
      
      this.concepts = new Map(data.concepts.map(([id, node]) => [
        id,
        {
          ...node,
          memoryIds: new Set(node.memoryIds),
          relatedConcepts: new Map(node.relatedConcepts)
        }
      ]));
      
      this.relationships = new Map(data.relationships);
      this.conceptIndex = new Map(data.conceptIndex.map(([id, arr]) => [id, new Set(arr)]));
      
      console.log(`[KnowledgeGraph] Loaded ${this.concepts.size} concepts, ${this.relationships.size} relationships`);
      return true;
    } catch (err) {
      console.error('[KnowledgeGraph] Load failed:', err.message);
      return false;
    }
  }

  addConcept(concept, memoryId, options = {}) {
    const normalized = this.normalizeConcept(concept);
    
    if (!this.concepts.has(normalized)) {
      this.concepts.set(normalized, {
        id: normalized,
        name: concept,
        frequency: 0,
        memoryIds: new Set(),
        relatedConcepts: new Map(),
        centrality: 0,
        createdAt: new Date().toISOString()
      });
      this.dirty = true;
    }
    
    const node = this.concepts.get(normalized);
    node.frequency++;
    node.memoryIds.add(memoryId);
    
    if (!this.conceptIndex.has(normalized)) {
      this.conceptIndex.set(normalized, new Set());
    }
    this.conceptIndex.get(normalized).add(memoryId);
    
    return node;
  }

  linkConcepts(from, to, type = 'related_to', strength = 0.5, evidence = []) {
    const fromNorm = this.normalizeConcept(from);
    const toNorm = this.normalizeConcept(to);
    
    if (fromNorm === toNorm) return null;
    
    const edgeId = `${fromNorm}__${type}__${toNorm}`;
    
    if (this.relationships.has(edgeId)) {
      const edge = this.relationships.get(edgeId);
      edge.strength = Math.max(edge.strength, strength);
      edge.evidence.push(...evidence);
      edge.updatedAt = new Date().toISOString();
    } else {
      this.relationships.set(edgeId, {
        id: edgeId,
        from: fromNorm,
        to: toNorm,
        type,
        strength,
        evidence: [...evidence],
        createdAt: new Date().toISOString()
      });
      this.dirty = true;
    }
    
    const fromNode = this.concepts.get(fromNorm);
    const toNode = this.concepts.get(toNorm);
    
    if (fromNode) {
      fromNode.relatedConcepts.set(toNorm, 
        Math.max(fromNode.relatedConcepts.get(toNorm) || 0, strength));
    }
    if (toNode) {
      toNode.relatedConcepts.set(fromNorm,
        Math.max(toNode.relatedConcepts.get(fromNorm) || 0, strength));
    }
    
    this.eventBus.publish(MemoryEvents.RELATIONSHIP_ADDED, {
      edgeId,
      from: fromNorm,
      to: toNorm,
      type,
      strength
    });
    
    return this.relationships.get(edgeId);
  }

  extractConcepts(text, maxConcepts = 20) {
    const concepts = new Set();
    
    const patterns = [
      /\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b/g,
      /\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b/g,
      /\b[a-z]+(?:-[a-z]+)+\b/gi,
      /\b[A-Z]{2,}\b/g,
      /"([^"]+)"/g,
      /`([^`]+)`/g
    ];
    
    for (const pattern of patterns) {
      const matches = text.matchAll(pattern);
      for (const match of matches) {
        concepts.add(match[1] || match[0]);
        if (concepts.size >= maxConcepts * 2) break;
      }
      if (concepts.size >= maxConcepts * 2) break;
    }
    
    const commonWords = new Set(['the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'had', 'her', 'was', 'one', 'our', 'out', 'day', 'get', 'has', 'him', 'his', 'how', 'its', 'may', 'new', 'now', 'old', 'see', 'two', 'who', 'boy', 'did', 'she', 'use', 'her', 'way', 'many', 'oil', 'sit', 'set', 'run', 'eat', 'far', 'sea', 'eye', 'ask', 'own', 'say', 'too', 'any']);
    
    return Array.from(concepts)
      .map(c => c.trim())
      .filter(c => c.length > 2 && !commonWords.has(c.toLowerCase()))
      .slice(0, maxConcepts);
  }

  /**
   * AI-enhanced concept extraction
   */
  async extractConceptsWithAI(content) {
    if (!this.intelligenceProvider?.extractGraphEntities) {
      return null;
    }
    
    try {
      return await this.intelligenceProvider.extractGraphEntities(content);
    } catch (err) {
      console.error('[KnowledgeGraph] AI extraction failed:', err.message);
      return null;
    }
  }

  async buildFromMemory(memoryId, content, tags = []) {
    let concepts = [];
    let relationships = [];
    
    // Try AI-enhanced extraction first
    const aiResult = await this.extractConceptsWithAI(content);
    
    if (aiResult && aiResult.concepts) {
      concepts = aiResult.concepts.slice(0, 15);
      relationships = (aiResult.relationships || []).slice(0, 30);
      console.log(`[KnowledgeGraph] AI extracted ${concepts.length} concepts, ${relationships.length} relationships for ${memoryId}`);
    } else {
      // Fallback to regex
      concepts = this.extractConcepts(content, 15);
    }
    
    // Add concept nodes
    for (const concept of concepts) {
      this.addConcept(concept, memoryId);
    }
    
    // Add tag-based concepts
    const limitedTags = tags.slice(0, 5);
    for (const tag of limitedTags) {
      this.addConcept(tag, memoryId);
    }
    
    // Link AI relationships
    if (relationships.length > 0) {
      for (const rel of relationships) {
        if (rel.from && rel.to) {
          this.linkConcepts(rel.from, rel.to, rel.type || 'related_to', rel.strength || 0.5, [memoryId]);
        }
      }
    } else {
      // Fallback: link co-occurring concepts
      let pairsCreated = 0;
      const maxPairs = 50;
      for (let i = 0; i < concepts.length && pairsCreated < maxPairs; i++) {
        for (let j = i + 1; j < concepts.length && pairsCreated < maxPairs; j++) {
          this.linkConcepts(concepts[i], concepts[j], 'co_occurs_with', 0.3, [memoryId]);
          pairsCreated++;
        }
      }
    }
    
    // Link concepts to tags
    let tagLinksCreated = 0;
    const maxTagLinks = 30;
    for (const concept of concepts) {
      for (const tag of limitedTags) {
        if (tagLinksCreated >= maxTagLinks) break;
        this.linkConcepts(concept, tag, 'tagged_as', 0.5, [memoryId]);
        tagLinksCreated++;
      }
      if (tagLinksCreated >= maxTagLinks) break;
    }
    
    await this.eventBus.publish(MemoryEvents.GRAPH_UPDATED, {
      memoryId,
      conceptsAdded: concepts.length,
      tagsAdded: tags.length
    });
    
    return {
      concepts: concepts.length,
      relationships: relationships.length > 0 ? relationships.length : (concepts.length * (concepts.length - 1)) / 2
    };
  }

  getRelatedConcepts(concept, depth = 1) {
    const normalized = this.normalizeConcept(concept);
    const visited = new Set();
    const results = [];
    
    const traverse = (current, currentDepth, path) => {
      if (currentDepth > depth) return;
      if (visited.has(current)) return;
      visited.add(current);
      
      const node = this.concepts.get(current);
      if (!node) return;
      
      results.push({
        concept: current,
        depth: currentDepth,
        path: [...path],
        strength: path.length > 0 
          ? path.reduce((sum, p) => sum + p.strength, 0) / path.length 
          : 1
      });
      
      for (const [related, strength] of node.relatedConcepts) {
        traverse(related, currentDepth + 1, [...path, { concept: related, strength }]);
      }
    };
    
    traverse(normalized, 0, []);
    return results;
  }

  findPath(from, to, maxDepth = 5) {
    const fromNorm = this.normalizeConcept(from);
    const toNorm = this.normalizeConcept(to);
    
    if (fromNorm === toNorm) return [fromNorm];
    
    const queue = [[{ concept: fromNorm, strength: 1 }]];
    const visited = new Set([fromNorm]);
    
    while (queue.length > 0) {
      const path = queue.shift();
      const current = path[path.length - 1].concept;
      
      if (path.length > maxDepth) continue;
      
      const node = this.concepts.get(current);
      if (!node) continue;
      
      for (const [related, strength] of node.relatedConcepts) {
        if (related === toNorm) {
          return [...path.map(p => p.concept), related];
        }
        
        if (!visited.has(related)) {
          visited.add(related);
          queue.push([...path, { concept: related, strength }]);
        }
      }
    }
    
    return null;
  }

  getMemoriesForConcept(concept) {
    const normalized = this.normalizeConcept(concept);
    return Array.from(this.conceptIndex.get(normalized) || []);
  }

  findMemoriesByConcepts(concepts, matchAll = false) {
    const sets = concepts.map(c => 
      this.conceptIndex.get(this.normalizeConcept(c)) || new Set()
    );
    
    if (sets.length === 0) return [];
    
    if (matchAll) {
      const result = new Set(sets[0]);
      for (let i = 1; i < sets.length; i++) {
        for (const item of result) {
          if (!sets[i].has(item)) {
            result.delete(item);
          }
        }
      }
      return Array.from(result);
    } else {
      const result = new Set();
      for (const set of sets) {
        for (const item of set) {
          result.add(item);
        }
      }
      return Array.from(result);
    }
  }

  detectClusters() {
    const clusters = [];
    const visited = new Set();
    
    for (const [concept, node] of this.concepts) {
      if (visited.has(concept)) continue;
      
      const cluster = new Set();
      const queue = [concept];
      
      while (queue.length > 0) {
        const current = queue.shift();
        if (visited.has(current)) continue;
        
        visited.add(current);
        cluster.add(current);
        
        const currentNode = this.concepts.get(current);
        if (currentNode) {
          for (const related of currentNode.relatedConcepts.keys()) {
            if (!visited.has(related)) {
              queue.push(related);
            }
          }
        }
      }
      
      if (cluster.size >= 3) {
        clusters.push(Array.from(cluster));
      }
    }
    
    return clusters.sort((a, b) => b.length - a.length);
  }

  computeCentrality() {
    const scores = new Map();
    
    for (const [concept, node] of this.concepts) {
      scores.set(concept, node.relatedConcepts.size);
    }
    
    for (const [concept, score] of scores) {
      const node = this.concepts.get(concept);
      if (node) {
        node.centrality = score;
      }
    }
    
    return scores;
  }

  getTopConcepts(limit = 20) {
    return Array.from(this.concepts.values())
      .sort((a, b) => (b.centrality + b.frequency) - (a.centrality + a.frequency))
      .slice(0, limit)
      .map(c => ({
        name: c.name,
        frequency: c.frequency,
        centrality: c.centrality,
        memoryCount: c.memoryIds.size
      }));
  }

  getPrerequisites(concept) {
    const normalized = this.normalizeConcept(concept);
    const prereqs = [];
    
    for (const [edgeId, edge] of this.relationships) {
      if (edge.to === normalized && edge.type === 'prerequisite_for') {
        prereqs.push({
          concept: edge.from,
          strength: edge.strength,
          evidence: edge.evidence
        });
      }
    }
    
    return prereqs.sort((a, b) => b.strength - a.strength);
  }

  suggestConnections(concept, limit = 5) {
    const normalized = this.normalizeConcept(concept);
    const node = this.concepts.get(normalized);
    if (!node) return [];
    
    const suggestions = new Map();
    
    for (const [related, strength] of node.relatedConcepts) {
      const relatedNode = this.concepts.get(related);
      if (!relatedNode) continue;
      
      for (const [potential, _] of relatedNode.relatedConcepts) {
        if (potential !== normalized && !node.relatedConcepts.has(potential)) {
          const current = suggestions.get(potential) || { score: 0, via: [] };
          current.score += strength;
          current.via.push(related);
          suggestions.set(potential, current);
        }
      }
    }
    
    return Array.from(suggestions.entries())
      .sort((a, b) => b[1].score - a[1].score)
      .slice(0, limit)
      .map(([concept, data]) => ({
        concept,
        score: data.score,
        via: data.via.slice(0, 3)
      }));
  }

  export(format = 'json') {
    const data = {
      concepts: Array.from(this.concepts.entries()).map(([id, node]) => ({
        id,
        name: node.name,
        frequency: node.frequency,
        centrality: node.centrality,
        memoryIds: Array.from(node.memoryIds)
      })),
      relationships: Array.from(this.relationships.values())
    };
    
    if (format === 'json') {
      return data;
    }
    
    if (format === 'dot') {
      let dot = 'digraph KnowledgeGraph {\n';
      for (const concept of data.concepts) {
        dot += `  "${concept.id}" [label="${concept.name}"];\n`;
      }
      for (const edge of data.relationships) {
        dot += `  "${edge.from}" -> "${edge.to}" [label="${edge.type}"];\n`;
      }
      dot += '}';
      return dot;
    }
    
    return data;
  }

  normalizeConcept(concept) {
    return concept
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '');
  }

  getStats() {
    return {
      concepts: this.concepts.size,
      relationships: this.relationships.size,
      conceptIndex: this.conceptIndex.size,
      avgConnections: this.concepts.size > 0 
        ? (this.relationships.size / this.concepts.size).toFixed(2)
        : 0
    };
  }
}
