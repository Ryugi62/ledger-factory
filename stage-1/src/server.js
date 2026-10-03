'use strict';
// Entry point: listen on 0.0.0.0:$PORT (default 8080).

const { createServer } = require('./transport/http');
const { createRoutes } = require('./transport/routes');

const port = Number(process.env.PORT) || 8080;
const server = createServer(createRoutes());
server.keepAliveTimeout = 65000;
server.listen(port, '0.0.0.0', () => console.log(`pocketful listening on 0.0.0.0:${port}`));

const stop = () => server.close(() => process.exit(0));
process.on('SIGTERM', stop);
process.on('SIGINT', stop);
