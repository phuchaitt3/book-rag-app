# Dev image for compose. Build context: the repository root (the pnpm workspace lives there).
FROM node:24-slim
RUN npm install -g pnpm@12.16.1
WORKDIR /app

# Dependencies first, so source edits don't invalidate this layer.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/
RUN pnpm install --frozen-lockfile

COPY apps/web apps/web
WORKDIR /app/apps/web
EXPOSE 3000
CMD ["pnpm", "dev", "--hostname", "0.0.0.0"]
