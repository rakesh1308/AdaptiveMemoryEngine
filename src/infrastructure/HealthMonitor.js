/**
 * HealthMonitor - System health monitoring and diagnostics
 * Tracks component status, performance metrics, and alerts
 */

import { EventBus, MemoryEvents } from './EventBus.js';

export class HealthMonitor {
  constructor(options = {}) {
    this.checks = new Map();
    this.status = 'healthy'; // healthy, degraded, critical
    this.checkInterval = options.checkInterval || 60000; // 1 minute
    this.alertHandlers = [];
    this.metrics = new Map();
    this.eventBus = options.eventBus || new EventBus();
    this.startTime = Date.now();
    
    this.startMonitoring();
  }

  /**
   * Register a health check
   */
  registerCheck(name, checkFn, options = {}) {
    this.checks.set(name, {
      fn: checkFn,
      critical: options.critical || false,
      interval: options.interval || this.checkInterval,
      lastRun: null,
      lastResult: null
    });
  }

  /**
   * Register alert handler
   */
  onAlert(handler) {
    this.alertHandlers.push(handler);
  }

  /**
   * Run all health checks
   */
  async runChecks() {
    const results = {};
    let healthy = 0;
    let degraded = 0;
    let critical = 0;

    for (const [name, check] of this.checks) {
      try {
        const startTime = Date.now();
        const result = await check.fn();
        const duration = Date.now() - startTime;

        check.lastRun = new Date().toISOString();
        check.lastResult = result;

        results[name] = {
          status: result.status || 'unknown',
          duration,
          details: result.details || {}
        };

        if (result.status === 'OK') healthy++;
        else if (result.status === 'DEGRADED') degraded++;
        else if (result.status === 'FAIL') {
          critical++;
          if (check.critical) {
            this.triggerAlert('critical', `Critical check failed: ${name}`, result);
          }
        }
      } catch (err) {
        results[name] = {
          status: 'ERROR',
          error: err.message
        };
        critical++;
      }
    }

    // Determine overall status
    if (critical > 0) this.status = 'critical';
    else if (degraded > 0) this.status = 'degraded';
    else this.status = 'healthy';

    return {
      status: this.status,
      timestamp: new Date().toISOString(),
      uptime: Math.floor((Date.now() - this.startTime) / 1000),
      summary: { healthy, degraded, critical },
      checks: results
    };
  }

  /**
   * Get current health status
   */
  getStatus() {
    return {
      status: this.status,
      timestamp: new Date().toISOString(),
      uptime: Math.floor((Date.now() - this.startTime) / 1000)
    };
  }

  /**
   * Record metric
   */
  recordMetric(name, value, labels = {}) {
    const key = `${name}:${JSON.stringify(labels)}`;
    
    if (!this.metrics.has(key)) {
      this.metrics.set(key, {
        name,
        labels,
        values: [],
        count: 0,
        sum: 0,
        min: Infinity,
        max: -Infinity
      });
    }
    
    const metric = this.metrics.get(key);
    metric.values.push(value);
    metric.count++;
    metric.sum += value;
    metric.min = Math.min(metric.min, value);
    metric.max = Math.max(metric.max, value);
    
    // Keep last 1000 values
    if (metric.values.length > 1000) {
      metric.values.shift();
    }
  }

  /**
   * Get metrics summary
   */
  getMetrics() {
    const result = {};
    
    for (const [key, metric] of this.metrics) {
      result[key] = {
        name: metric.name,
        labels: metric.labels,
        count: metric.count,
        sum: metric.sum,
        avg: metric.sum / metric.count,
        min: metric.min,
        max: metric.max,
        last: metric.values[metric.values.length - 1]
      };
    }
    
    return result;
  }

  /**
   * Export metrics in Prometheus format
   */
  exportPrometheus() {
    const lines = [];
    
    for (const [key, metric] of this.metrics) {
      const labelStr = Object.entries(metric.labels)
        .map(([k, v]) => `${k}="${v}"`)
        .join(',');
      
      lines.push(`# HELP ${metric.name} ${metric.name} metric`);
      lines.push(`# TYPE ${metric.name} gauge`);
      lines.push(`${metric.name}{${labelStr}} ${metric.values[metric.values.length - 1] || 0}`);
    }
    
    return lines.join('\n');
  }

  /**
   * Trigger alert
   */
  triggerAlert(level, message, details = {}) {
    const alert = {
      level,
      message,
      details,
      timestamp: new Date().toISOString()
    };
    
    console.error(`[HealthMonitor] ${level.toUpperCase()}: ${message}`);
    
    for (const handler of this.alertHandlers) {
      try {
        handler(alert);
      } catch (err) {
        console.error('[HealthMonitor] Alert handler error:', err);
      }
    }
    
    this.eventBus.publish(MemoryEvents.ERROR_OCCURRED, alert);
  }

  /**
   * Start periodic monitoring
   */
  startMonitoring() {
    setInterval(async () => {
      await this.runChecks();
    }, this.checkInterval);
  }

  /**
   * Run diagnostics
   */
  async runDiagnostics() {
    const diagnostics = {
      timestamp: new Date().toISOString(),
      checks: {},
      recommendations: []
    };

    for (const [name, check] of this.checks) {
      try {
        const result = await check.fn();
        diagnostics.checks[name] = result;

        // Generate recommendations
        if (result.status === 'FAIL' && result.recommendation) {
          diagnostics.recommendations.push({
            component: name,
            issue: result.details?.error || 'Check failed',
            recommendation: result.recommendation
          });
        }
      } catch (err) {
        diagnostics.checks[name] = {
          status: 'ERROR',
          error: err.message
        };
      }
    }

    return diagnostics;
  }
}

/**
 * Predefined health checks
 */
export const HealthChecks = {
  storage: (engine) => async () => {
    const stats = engine.jsonlBackend.getStats();
    const issues = [];
    
    if (stats.memoryFile.size > 100 * 1024 * 1024) { // 100MB
      issues.push('Memory file exceeds 100MB, consider compaction');
    }
    
    if (stats.walFile.size > 50 * 1024 * 1024) { // 50MB
      issues.push('WAL file is large, checkpoint needed');
    }
    
    return {
      status: issues.length === 0 ? 'OK' : 'DEGRADED',
      details: stats,
      issues
    };
  },

  memory: (engine) => async () => {
    const memStats = engine.getStats();
    
    return {
      status: 'OK',
      details: {
        memories: memStats.totalMemories,
        chunks: memStats.totalChunks,
        embeddings: memStats.totalEmbeddings,
        concepts: memStats.totalConcepts
      }
    };
  },

  embeddings: (engine) => async () => {
    const stats = engine.vectorStore.getStats();
    
    if (!engine.options.embeddingProvider?.isAvailable?.()) {
      return {
        status: 'DEGRADED',
        details: stats,
        message: 'Embedding provider not available - running in keyword mode'
      };
    }
    
    return {
      status: 'OK',
      details: stats
    };
  },

  knowledgeGraph: (engine) => async () => {
    const stats = engine.knowledgeGraph.getStats();
    
    return {
      status: 'OK',
      details: stats
    };
  }
};
