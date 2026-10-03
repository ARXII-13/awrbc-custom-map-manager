# The intake server.
#
# A container rather than a platform's own build pack, because this process is
# two runtimes: Node serves the endpoint and Python decides what a valid map
# is (see prepare.ts for why that split exists). Nothing serverless fits - the
# server spawns `awrbc` per upload, so it needs a real process with a real
# PATH, not a function.
#
# That also means this runs anywhere a container does: Fly, Render, Railway, a
# VPS with compose. Nothing in here names a host.
#
#     docker build -f server/Dockerfile -t awrbc-intake .
#     docker run --rm -p 5000:5000 --env-file server/.env awrbc-intake
#
# Built from the repository root, not from server/: the image needs the Python
# package too, and a Docker build cannot reach above its context.

# --- build the TypeScript ----------------------------------------------
FROM node:22-slim AS build
WORKDIR /app

COPY server/package.json server/package-lock.json ./
RUN npm ci

COPY server/tsconfig.json ./
COPY server/src ./src
RUN npm run build && npm prune --omit=dev

# --- the thing that runs -----------------------------------------------
FROM node:22-slim
WORKDIR /app

# Python for the validator. --no-install-recommends keeps this to what is
# actually needed; the image is a server, not a workstation.
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-pip \
 && rm -rf /var/lib/apt/lists/*

# The validator itself, installed so `awrbc` is on PATH - which is the whole
# of the contract prepare.ts depends on. Only what the package needs is
# copied, so editing the editor or the docs does not invalidate this layer.
COPY pyproject.toml README.md /src/
COPY awrbc /src/awrbc
RUN pip3 install --no-cache-dir --break-system-packages /src \
 && awrbc --help > /dev/null

COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
# Load-bearing, not leftover: package.json carries `"type": "module"`, and
# without it node reads dist/*.js as CommonJS and dies on the first import.
COPY server/package.json ./

# Not root. This holds a token that can write to the archive.
RUN useradd --create-home --uid 10001 intake
USER intake

ENV NODE_ENV=production
ENV PORT=5000
EXPOSE 5000

# This only says the process is listening. /health answers 200 whenever it is
# up, including unconfigured - it reports `configured` and `missing` in the
# body rather than refusing, because a server with no Discord secret is a
# server somebody still needs to be able to reach and diagnose.
#
# The validator is not checked here because it cannot reach this far: `awrbc
# --help` runs at build time above, and index.ts exits 1 at startup if the
# command is not runnable. A container missing its validator never listens.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:'+(process.env.PORT||5000)+'/health').then(r=>r.ok?process.exit(0):process.exit(1)).catch(()=>process.exit(1))"

CMD ["node", "dist/index.js"]
