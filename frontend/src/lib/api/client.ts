const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? '';

interface ApiErrorEnvelope {
  error?: {
    code?: string;
    message?: string;
  };
}

const errorCodeMessages: Record<string, string> = {
  tail_radar_run_not_found: '尚未生成尾盘雷达运行记录。',
  tail_radar_candidate_not_found: '找不到该候选标的。',
  tail_radar_on_demand_research_disabled: '按需 AI 研究尚未在后端启用。',
  tail_radar_on_demand_research_unavailable: '按需 AI 研究配置不完整，请检查后端环境变量。',
  tail_radar_user_api_key_required: '请输入你自己的 OpenAI 接口密钥。',
  tail_radar_research_in_progress: '这只股票的 AI 研究已经在执行，请稍后刷新。',
  tail_radar_research_retry_confirmation_required:
    '上一次 AI 研究失败；再次调用可能产生费用，请明确确认重试。',
  research_provider_timeout: 'AI 研究请求超时，本次候选已标记失败。',
  research_provider_rate_limit: 'OpenAI 请求已达到速率限制，请稍后再试。',
  research_provider_authentication_error: 'OpenAI 拒绝了该接口密钥，请检查密钥和项目权限。',
  research_provider_unavailable: 'OpenAI 服务当前不可用，请稍后再试。',
  research_provider_api_error: 'OpenAI 拒绝了请求参数；请稍后重试，若仍失败请联系站点管理员。',
  research_provider_invalid_response: 'AI 返回内容未通过结构或时点完整性校验。',
  validation_error: '请求参数无效。',
};

function localizedErrorMessage(status: number, code: string | undefined): string {
  if (code && errorCodeMessages[code]) return errorCodeMessages[code];
  if (status === 400) return '请求内容无效。';
  if (status === 401 || status === 403) return '当前请求没有访问权限。';
  if (status === 404) return '请求的数据不存在。';
  if (status === 429) return '请求过于频繁，请稍后重试。';
  if (status >= 500) return '服务暂时不可用，请稍后重试。';
  return `请求失败（状态码 ${String(status)}）。`;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code = 'api_error',
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set('Accept', 'application/json');

  const response = await fetch(`${configuredBaseUrl}${path}`, {
    ...init,
    headers,
  });

  if (!response.ok) {
    let payload: ApiErrorEnvelope = {};
    try {
      payload = (await response.json()) as ApiErrorEnvelope;
    } catch {
      // A non-JSON upstream response is represented by the generic message below.
    }
    throw new ApiError(
      localizedErrorMessage(response.status, payload.error?.code),
      response.status,
      payload.error?.code,
    );
  }

  return (await response.json()) as T;
}

export const apiClient = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown, headers?: HeadersInit) =>
    request<T>(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...Object.fromEntries(new Headers(headers)) },
      body: JSON.stringify(body),
    }),
};
