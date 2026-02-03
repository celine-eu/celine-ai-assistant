FROM node:20-alpine

WORKDIR /app

COPY package.json /app/package.json
COPY svelte.config.js /app/svelte.config.js
COPY vite.config.ts /app/vite.config.ts
COPY tsconfig.json /app/tsconfig.json

RUN npm install

COPY src /app/src

EXPOSE 5173
CMD ["npm", "run", "dev"]
