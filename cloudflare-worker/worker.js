/**
 * Cloudflare Worker for SearXNG Anonymous Proxy View
 * Fetches target web pages directly from Cloudflare Anycast edge servers,
 * concealing origin IP and eliminating dyno memory/bandwidth usage.
 */

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // Health check endpoint
    if (url.pathname === "/healthz" || url.pathname === "/ping") {
      return new Response("OK", { status: 200 });
    }

    const target = url.searchParams.get("url");
    const h = url.searchParams.get("h");
    const t = url.searchParams.get("t");
    const jsEnabled = url.searchParams.get("js") === "1";

    if (!target) {
      return new Response("Missing target url parameter", { status: 400 });
    }

    // Read secret key from environment or fallback
    const secretKey = env.SEARXNG_SECRET || "";

    // 1. Verify HMAC token if secret is configured
    if (secretKey) {
      if (!h || !t) {
        return new Response("Unauthorized: missing security token", { status: 401 });
      }

      // Check token expiry (2 hours = 7200s)
      const now = Math.floor(Date.now() / 1000);
      const tokenTime = parseInt(t, 10);
      if (isNaN(tokenTime) || Math.abs(now - tokenTime) > 7200) {
        return new Response("Forbidden: token expired", { status: 403 });
      }

      // Verify HMAC-SHA256 signature
      const valid = await verifyHmac(secretKey, `${target}:${t}`, h);
      if (!valid) {
        return new Response("Forbidden: invalid token signature", { status: 403 });
      }
    }

    // 2. Validate URL schema
    let targetUrl;
    try {
      targetUrl = new URL(target);
      if (targetUrl.protocol !== "http:" && targetUrl.protocol !== "https:") {
        return new Response("Invalid protocol", { status: 400 });
      }
    } catch {
      return new Response("Invalid URL format", { status: 400 });
    }

    // 3. Block private / internal IP ranges (SSRF protection)
    const hostname = targetUrl.hostname.toLowerCase();
    if (
      hostname === "localhost" ||
      hostname === "127.0.0.1" ||
      hostname === "0.0.0.0" ||
      hostname === "::1" ||
      hostname.startsWith("10.") ||
      hostname.startsWith("192.168.") ||
      hostname.startsWith("169.254.") ||
      hostname.endsWith(".internal") ||
      hostname.endsWith(".local")
    ) {
      return new Response("Access to private/local destinations is blocked", { status: 403 });
    }

    // 4. Fetch target website from Cloudflare edge
    let response;
    try {
      response = await fetch(target, {
        headers: {
          "User-Agent":
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
          "Accept":
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
          "Accept-Language": "en-US,en;q=0.9",
        },
        redirect: "follow",
      });
    } catch (err) {
      return new Response(`Proxy fetch error: ${err.message}`, { status: 502 });
    }

    // 5. Prepare sanitised response headers
    const headers = new Headers(response.headers);
    // Strip frame busters
    headers.delete("x-frame-options");
    headers.delete("content-security-policy");
    headers.delete("content-security-policy-report-only");
    headers.delete("x-content-security-policy");
    headers.delete("clear-site-data");

    // Anonymous referrer & permissive frame embedding
    headers.set("referrer-policy", "no-referrer");
    headers.set("access-control-allow-origin", "*");
    headers.set("x-proxied-by", "SearXNG-Cloudflare-Worker");

    const contentType = (headers.get("content-type") || "").toLowerCase();

    // 6. For HTML content: inject <base> tag and optional script stripping
    if (contentType.includes("text/html")) {
      let rewriter = new HTMLRewriter()
        .on("head", {
          element(el) {
            el.prepend(`<base href="${escapeHtml(target)}">`, { html: true });
            el.prepend('<meta name="referrer" content="no-referrer">', { html: true });
          },
        })
        .on("a", {
          element(el) {
            // Force links to open in a new tab if clicked inside iframe
            const targetAttr = el.getAttribute("target");
            if (!targetAttr || targetAttr === "_self") {
              el.setAttribute("target", "_blank");
            }
          },
        });

      if (!jsEnabled) {
        rewriter = rewriter.on("script", {
          element(el) {
            el.remove();
          },
        });
      }

      return rewriter.transform(
        new Response(response.body, {
          status: response.status,
          headers,
        })
      );
    }

    // Non-HTML content: stream directly
    return new Response(response.body, {
      status: response.status,
      headers,
    });
  },
};

/**
 * Verify HMAC-SHA256 signature in constant time
 */
async function verifyHmac(secret, message, expectedHex) {
  try {
    const encoder = new TextEncoder();
    const key = await crypto.subtle.importKey(
      "raw",
      encoder.encode(secret),
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["verify"]
    );
    const expectedBytes = new Uint8Array(
      expectedHex.match(/.{1,2}/g).map((byte) => parseInt(byte, 16))
    );
    return await crypto.subtle.verify("HMAC", key, expectedBytes, encoder.encode(message));
  } catch {
    return false;
  }
}

function escapeHtml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
