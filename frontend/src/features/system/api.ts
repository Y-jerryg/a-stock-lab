import { apiClient } from '../../lib/api/client';

export interface HealthResponse {
  status: 'ok' | 'degraded';
  service: string;
  version: string;
  generated_at: string;
  database: { status: 'available' | 'unavailable' };
}

export function getHealth() {
  return apiClient.get<HealthResponse>('/api/v1/health');
}
