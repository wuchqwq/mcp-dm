#!/usr/bin/env node
/** DM-free MCP entry point: independent TIFF/image analysis and optional structures. */
import process from 'node:process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {startStdioMcpServer} from './lib/runtime/stdio_mcp_server.mjs';
import {createScienceRuntime} from './lib/science/create_science_runtime.mjs';

export function startScienceServer({runtime=createScienceRuntime(),...options}={}){
  return startStdioMcpServer({runtime,serverName:'microscopy-core',serverVersion:'0.1.0',...options});
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))startScienceServer();
