// Mirrors mealsight/api/health.py's own build_health_report return shape.

export interface McpServerHealth {
  status: 'up' | 'down'
  tool_count?: number
  missing_tools?: string[]
  detail?: string
}

export interface ProviderHealth {
  status: 'up' | 'down'
  detail?: string
}

export interface RecipeDatabaseHealth {
  status: 'up' | 'down'
  recipe_count?: number
  detail?: string
}

/** GET /health's own response — 503 (same body shape) when anything is down. */
export interface HealthReport {
  status: 'healthy' | 'degraded'
  mcp_servers: Record<string, McpServerHealth>
  providers: {
    mistral: ProviderHealth
    groq: ProviderHealth
  }
  recipe_database: RecipeDatabaseHealth
}
