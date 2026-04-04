/**
 * ProviderFactory - Creates embedding and intelligence providers from configuration
 * 
 * Supports:
 * - OpenAI (openai)
 * - Ollama (ollama) - local models
 * - Google Gemini (gemini)
 * - Anthropic Claude (anthropic) - for intelligence only
 * - Custom providers
 * 
 * Usage:
 *   const provider = ProviderFactory.create({
 *     type: 'ollama',
 *     embeddingModel: 'nomic-embed-text',
 *     chatModel: 'llama3.2'
 *   });
 */

import { OpenAIProvider } from './OpenAIProvider.js';
import { OllamaProvider } from './OllamaProvider.js';
import { GeminiProvider } from './GeminiProvider.js';
import { AnthropicProvider } from './AnthropicProvider.js';

export class ProviderFactory {
  static PROVIDERS = {
    openai: OpenAIProvider,
    ollama: OllamaProvider,
    gemini: GeminiProvider,
    anthropic: AnthropicProvider
  };

  /**
   * Create a provider instance
   * @param {Object} config - Provider configuration
   * @param {string} config.type - Provider type (openai, ollama, gemini, anthropic)
   * @param {string} config.apiKey - API key (if needed)
   * @param {string} config.baseUrl - Custom base URL
   * @param {string} config.embeddingModel - Model for embeddings
   * @param {string} config.chatModel - Model for chat/intelligence
   * @returns {EmbeddingProvider|IntelligentProvider}
   */
  static create(config = {}) {
    const type = config.type || this.detectFromEnv();
    const ProviderClass = this.PROVIDERS[type.toLowerCase()];
    
    if (!ProviderClass) {
      throw new Error(
        `Unknown provider type: ${type}. ` +
        `Supported: ${Object.keys(this.PROVIDERS).join(', ')}`
      );
    }

    return new ProviderClass({
      apiKey: config.apiKey || this.getApiKeyForType(type),
      baseUrl: config.baseUrl,
      embeddingModel: config.embeddingModel,
      chatModel: config.chatModel,
      ...config
    });
  }

  /**
   * Register a custom provider
   * @param {string} name - Provider name
   * @param {Class} ProviderClass - Provider class extending EmbeddingProvider
   */
  static register(name, ProviderClass) {
    this.PROVIDERS[name.toLowerCase()] = ProviderClass;
  }

  /**
   * Detect provider type from environment variables
   * @returns {string}
   */
  static detectFromEnv() {
    if (process.env.OLLAMA_HOST || process.env.OLLAMA_MODEL) return 'ollama';
    if (process.env.GEMINI_API_KEY) return 'gemini';
    if (process.env.ANTHROPIC_API_KEY) return 'anthropic';
    if (process.env.OPENAI_API_KEY) return 'openai';
    
    // Default to OpenAI if nothing specified
    return 'openai';
  }

  /**
   * Get API key for provider type from environment
   * @param {string} type - Provider type
   * @returns {string|undefined}
   */
  static getApiKeyForType(type) {
    const keyMap = {
      openai: process.env.OPENAI_API_KEY,
      gemini: process.env.GEMINI_API_KEY,
      anthropic: process.env.ANTHROPIC_API_KEY,
      ollama: null // Ollama typically doesn't need an API key for local use
    };
    return keyMap[type.toLowerCase()];
  }

  /**
   * Get available providers and their status
   * @returns {Array<{name: string, available: boolean, config: Object}>}
   */
  static listAvailable() {
    return Object.entries(this.PROVIDERS).map(([name, ProviderClass]) => {
      const provider = new ProviderClass({});
      return {
        name,
        available: provider.isAvailable(),
        config: provider.getConfig?.() || {}
      };
    });
  }

  /**
   * Validate provider configuration
   * @param {Object} config - Configuration to validate
   * @returns {{valid: boolean, errors: string[]}}
   */
  static validateConfig(config = {}) {
    const errors = [];
    
    if (!config.type) {
      errors.push('Provider type is required');
    } else if (!this.PROVIDERS[config.type.toLowerCase()]) {
      errors.push(`Unknown provider type: ${config.type}`);
    }

    // Check for required API keys
    const apiKey = config.apiKey || this.getApiKeyForType(config.type);
    const needsKey = ['openai', 'gemini', 'anthropic'].includes(config.type?.toLowerCase());
    
    if (needsKey && !apiKey) {
      errors.push(`API key required for ${config.type} provider`);
    }

    return {
      valid: errors.length === 0,
      errors
    };
  }
}
