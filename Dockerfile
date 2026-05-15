FROM node:22-slim

WORKDIR /app

COPY package*.json ./
RUN npm install --omit=dev

COPY . .

# Create data directory for SQLite
RUN mkdir -p /app/data

# Set default env variables for Cloud Run
ENV TRANSPORT=http
ENV PORT=8080
ENV DATA_DIR=/app/data

EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD node -e "fetch('http://localhost:8080/health').then(r => r.ok || process.exit(1))"

CMD ["npm", "start"]