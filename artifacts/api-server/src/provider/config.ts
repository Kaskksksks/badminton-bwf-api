export class ProviderConfigurationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ProviderConfigurationError";
  }
}

export interface ProviderConfig {
  baseUrl: string;
}

/**
 * The provider URL is intentionally read only on the server. There is no
 * public default: a missing setting must become a truthful configuration
 * error instead of silently targeting a different deployment.
 */
export function getProviderConfig(
  env: NodeJS.ProcessEnv = process.env,
): ProviderConfig {
  const raw = env["BADMINTON_API_BASE_URL"]?.trim();
  if (!raw) {
    throw new ProviderConfigurationError(
      "BADMINTON_API_BASE_URL is required for provider reads.",
    );
  }

  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    throw new ProviderConfigurationError(
      "BADMINTON_API_BASE_URL must be an absolute http(s) URL.",
    );
  }

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new ProviderConfigurationError(
      "BADMINTON_API_BASE_URL must use http or https.",
    );
  }

  return { baseUrl: parsed.toString().replace(/\/+$/, "") };
}