FROM node:22-alpine

WORKDIR /app
ENV NODE_ENV=production \
    PORT=8080 \
    UV_THREADPOOL_SIZE=8

# No third-party dependencies: the service uses only the Node.js standard library.
COPY package.json ./
COPY src ./src
COPY test ./test

USER node
EXPOSE 8080
CMD ["node", "--max-old-space-size=1536", "src/server.js"]
