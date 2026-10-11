const http = require('http');
const net = require('net');

const PORT = 8088;
const TARGET_HOST = '127.0.0.1';
const TARGET_PORT = 8001;

const server = http.createServer((req, res) => {
  // Add CORS headers just in case
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', '*');
  res.setHeader('Access-Control-Allow-Headers', '*');

  if (req.method === 'OPTIONS') {
    res.writeHead(200);
    res.end();
    return;
  }

  const options = {
    hostname: TARGET_HOST,
    port: TARGET_PORT,
    path: req.url,
    method: req.method,
    headers: {
      ...req.headers,
      host: `${TARGET_HOST}:${TARGET_PORT}`,
    },
  };

  const proxyReq = http.request(options, (proxyRes) => {
    res.writeHead(proxyRes.statusCode, proxyRes.headers);
    proxyRes.pipe(res, { end: true });
  });

  proxyReq.on('error', (err) => {
    console.error('Proxy request error:', err.message);
    if (!res.headersSent) {
      res.writeHead(502, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Backend unreachable', details: err.message }));
    }
  });

  req.pipe(proxyReq, { end: true });
});

// Support WebSocket Upgrade
server.on('upgrade', (req, clientSocket, head) => {
  const targetSocket = net.connect(TARGET_PORT, TARGET_HOST, () => {
    const rawHeaders = Object.entries(req.headers)
      .map(([key, val]) => `${key}: ${Array.isArray(val) ? val.join(', ') : val}`)
      .join('\r\n');
    targetSocket.write(`${req.method} ${req.url} HTTP/${req.httpVersion}\r\n${rawHeaders}\r\n\r\n`);
    if (head && head.length) targetSocket.write(head);
    clientSocket.pipe(targetSocket);
    targetSocket.pipe(clientSocket);
  });

  targetSocket.on('error', (err) => {
    console.error('WS target error:', err.message);
    clientSocket.destroy();
  });
  clientSocket.on('error', (err) => {
    console.error('WS client error:', err.message);
    targetSocket.destroy();
  });
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`[Mobile Proxy] Running on http://0.0.0.0:${PORT} -> http://${TARGET_HOST}:${TARGET_PORT}`);
});
