// cookie-session attaches to the request; this says what we keep in it.
import type { Identity } from './discord.js';

declare global {
  namespace Express {
    interface Request {
      session?: CookieSessionInterfaces.CookieSessionObject & {
        user?: Identity;
        oauthState?: string | undefined;
        afterLogin?: string | undefined;
      } | null;
    }
  }
}

export {};
