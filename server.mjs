#!/usr/bin/env node
/** DigitalMicrograph compatibility entry point. Existing tool names, backend
 * selection and initialized server identity remain unchanged. */
import process from 'node:process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createServerRuntime} from './lib/tools/create_server_runtime.mjs';
import {startStdioMcpServer} from './lib/runtime/stdio_mcp_server.mjs';

export function startMcpServer({runtime=createServerRuntime(),...options}={}){
  return startStdioMcpServer({runtime,serverName:'digitalmicrograph',serverVersion:'0.6.0',...options});
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))startMcpServer();
