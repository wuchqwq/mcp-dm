import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {spawnSync} from 'node:child_process';
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'mcp-canonical-review-'));
const root=path.join(temp,'workspace');fs.mkdirSync(root);
try {
 const p=spawnSync('python',['-c',`import pathlib,json,sys
root=pathlib.Path(sys.argv[1]).resolve()
file=root/'preview.png';file.write_bytes(b'png')
print(json.dumps({'root':str(root),'file':str(file)}))`,root],{encoding:'utf8'});
 if(p.status!==0)throw Error(p.stderr);
 const returned=JSON.parse(p.stdout);
 const roots={input:root,js:fs.realpathSync(root),native:fs.realpathSync.native(root),python:returned.root};
 const files={python:returned.file,js:fs.realpathSync(returned.file),native:fs.realpathSync.native(returned.file)};
 console.log(JSON.stringify({platform:process.platform,tmpdir:os.tmpdir(),roots,files,
   relative_js:path.relative(roots.js,files.js),relative_native:path.relative(roots.native,files.native)},null,2));
} finally {fs.rmSync(temp,{recursive:true,force:true});}
