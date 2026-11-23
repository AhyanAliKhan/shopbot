// Point this at your deployed Agent API (Render URL), no trailing slash.
window.SHOPBOT_API =
  location.hostname === "localhost" || location.hostname === "127.0.0.1" || location.protocol === "file:"
    ? "http://localhost:8000"
    : "https://shopbot-pnm5.onrender.com";
