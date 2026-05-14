FROM node:22-slim

WORKDIR /app

COPY package*.json ./
RUN npm install --omit=dev

COPY . .

# Set default env variables for Cloud Run
ENV TRANSPORT=http
ENV PORT=8080

EXPOSE 8080
CMD ["npm", "start"]
