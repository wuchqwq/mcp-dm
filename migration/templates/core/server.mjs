#!/usr/bin/env node
// Portable default entry, including the no-model Image Panel's stdio client.
// This file never imports the legacy DM composition root.
import process from 'node:process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {startScienceServer} from './science-server.mjs';
export {startScienceServer as startMcpServer};
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))startScienceServer();
