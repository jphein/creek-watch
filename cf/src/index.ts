// Creek Watch on Cloudflare: one Container running the existing FastAPI image, fronted by this Worker.
// - every app request goes to ONE container instance (Durable Object "main") => exactly one SQLite writer
// - /uploads/<hex>.jpg is served straight from R2 (photos never depend on the container being up)
// - a Cron Trigger calls the protected /internal/poll every 5 min (alert poller + keep-alive)
import { Container } from "@cloudflare/containers";

export interface Env {
  CW: DurableObjectNamespace<CreekWatch>;
  PHOTOS: R2Bucket;
  // secrets (wrangler secret put ...), never in config:
  INTERNAL_TOKEN: string;
  CREEKWATCH_VAPID_PRIVATE: string;
  CREEKWATCH_VAPID_PUBLIC: string;
  R2_ACCESS_KEY_ID: string;
  R2_SECRET_ACCESS_KEY: string;
  // vars:
  R2_ENDPOINT: string;
  R2_BUCKET: string;
  PUBLIC_URL: string;
}

const UPLOAD_RE = /^\/uploads\/([0-9a-f]{32}\.jpg)$/;

export class CreekWatch extends Container<Env> {
  defaultPort = 8080;
  sleepAfter = "2h"; // the 5-min cron keeps it warm; a long idle timeout avoids cold starts for visitors

  constructor(ctx: DurableObjectState<{}>, env: Env) {
    super(ctx, env);
    this.envVars = {
      CREEKWATCH_PUBLIC_URL: env.PUBLIC_URL,
      CREEKWATCH_VAPID_PRIVATE: env.CREEKWATCH_VAPID_PRIVATE,
      CREEKWATCH_VAPID_PUBLIC: env.CREEKWATCH_VAPID_PUBLIC,
      CREEKWATCH_VAPID_SUBJECT: "https://creekwatch.realm.watch",
      CREEKWATCH_INTERNAL_TOKEN: env.INTERNAL_TOKEN,
      CREEKWATCH_UPLOADS_BACKEND: "r2",
      CREEKWATCH_R2_ENDPOINT: env.R2_ENDPOINT,
      CREEKWATCH_R2_BUCKET: env.R2_BUCKET,
      CREEKWATCH_R2_ACCESS_KEY_ID: env.R2_ACCESS_KEY_ID,
      CREEKWATCH_R2_SECRET_ACCESS_KEY: env.R2_SECRET_ACCESS_KEY,
      // The Worker is the container's only ingress and Cloudflare's edge overwrites CF-Connecting-IP with
      // the real client address, so the app may trust it from any peer (per-device rate limits).
      CREEKWATCH_TRUSTED_PROXIES: "0.0.0.0/0,::/0",
    };
  }
}

function app(env: Env) {
  return env.CW.getByName("main"); // single instance, single writer
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const m = UPLOAD_RE.exec(url.pathname);
    if (m && (request.method === "GET" || request.method === "HEAD")) {
      const obj = await env.PHOTOS.get(`uploads/${m[1]}`);
      if (!obj) return new Response("Not Found", { status: 404 });
      return new Response(request.method === "HEAD" ? null : obj.body, {
        headers: {
          "content-type": "image/jpeg",
          "cache-control": "public, max-age=31536000, immutable",
          etag: obj.httpEtag,
        },
      });
    }
    if (url.pathname.startsWith("/internal/")) return new Response("Not Found", { status: 404 }); // cron only
    return app(env).fetch(request);
  },

  async scheduled(_event: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    ctx.waitUntil(
      app(env)
        .fetch(new Request("http://container/internal/poll", {
          method: "POST",
          headers: { "x-internal-token": env.INTERNAL_TOKEN },
        }))
        .then(async (r) => console.log("poll", r.status, (await r.text()).slice(0, 300))),
    );
  },
};
