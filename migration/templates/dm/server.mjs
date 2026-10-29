#!/usr/bin/env node
import process from 'node:process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {startStdioMcpServer} from './lib/runtime/stdio_mcp_server.mjs';
import {createDMRuntime} from './lib/tools/create_dm_runtime.mjs';
export function startMcpServer({runtime=createDMRuntime(),...options}={}) {
  return startStdioMcpServer({runtime,serverName:'digitalmicrograph',serverVersion:'0.6.0',...options});
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))startMcpServer();
