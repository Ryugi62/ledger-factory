'use strict';

// An error that maps directly onto the §5 error envelope.
class ApiError extends Error {
  constructor(status, code, message) {
    super(message || code);
    this.status = status;
    this.code = code;
  }
}

const malformed = (msg) => new ApiError(400, 'malformed_request', msg || 'malformed request');
const invalid = (msg) => new ApiError(422, 'validation_failed', msg || 'validation failed');
const notFound = (msg) => new ApiError(404, 'not_found', msg || 'not found');
const forbidden = (msg) => new ApiError(403, 'forbidden', msg || 'forbidden');
const unauthenticated = (msg) => new ApiError(401, 'unauthenticated', msg || 'unauthenticated');
const conflict = (code, msg) => new ApiError(409, code, msg || code);

module.exports = { ApiError, malformed, invalid, notFound, forbidden, unauthenticated, conflict };
