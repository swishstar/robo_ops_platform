/// <reference types="vite/client" />

interface RrOpsConfig {
  apiBase: string;
}

interface Window {
  __RR_OPS_CONFIG__?: RrOpsConfig;
}
