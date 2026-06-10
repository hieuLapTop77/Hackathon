const getApiUrl = () => {
  const envUrl = import.meta.env.VITE_API_URL;
  
  // If it's a relative path (e.g. "/api"), return it directly
  if (envUrl && envUrl.startsWith("/")) {
    return envUrl;
  }
  
  if (typeof window !== "undefined" && window.location) {
    const hostname = window.location.hostname;
    const protocol = window.location.protocol;
    
    // Default to port 8020 for H200 server, or extract from VITE_API_URL if configured
    let port = "8020";
    if (envUrl) {
      try {
        const parsedUrl = new URL(envUrl);
        if (parsedUrl.port) {
          port = parsedUrl.port;
        }
      } catch (e) {
        const match = envUrl.match(/:(\d+)/);
        if (match) {
          port = match[1];
        }
      }
    }
    return `${protocol}//${hostname}:${port}/api`;
  }
  
  return envUrl || "http://localhost:8020/api";
};

export const API_BASE_URL = getApiUrl();
