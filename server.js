import express from 'express';
import cors from 'cors';
import apiRouter from './server/routers.js';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();

app.use(cors());
app.use(express.json());

// API Routes
app.use('/api/v1', apiRouter);

// Serve static frontend in production
if (process.env.NODE_ENV === 'production') {
  app.use(express.static(path.join(__dirname, 'client/dist')));
  app.get('*', (req, res) => {
    res.sendFile(path.join(__dirname, 'client/dist/index.html'));
  });
}

// In dev, Vite handles port 3000 and proxies to this server on 3001.
// In prod, Vite is built, and this Express server serves everything on port 3000.
const port = process.env.NODE_ENV === 'production' ? 3000 : 3001;

app.listen(port, '0.0.0.0', () => {
  console.log(`Express server running on port ${port}`);
});
