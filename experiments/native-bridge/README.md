# nb_probe — native plugin round-trip probe

A deliberately narrow native plugin used to answer one question:

> can an external request be carried into DigitalMicrograph's own thread, executed there,
> and answered with an auditable receipt — without resident Python?

It is a **probe**, not a bridge. It does no image work, registers no script functions, and is
not supported by Gatan. Everything here is a build-specific experiment.

## What it does

```
external client ──named pipe──▶ worker thread          (parse, validate, enqueue only)
                                    │  PostMessage
                                    ▼
                              hidden window WndProc     (host thread; the only place that
                                    │                    touches host state)
                                    ▼
                              receipt ──named pipe──▶ client
```

The receipt carries the request id, four phase timestamps (µs), the worker thread id and the
thread id that actually executed the request. Comparing that last value with the thread id
logged at `PlugInStartup` is the point of the exercise.

## Protocol

One ASCII line per request, one line per reply.

| Request | Reply |
|---|---|
| `PING <id>` | `OK <id> <recv→post> <post→exec> <exec> <…> <result> <worker_tid> <exec_tid>` |
| `STOP` | `BYE`, then the pipe stops listening |
| anything else | `ERR bad-request` |
| host did not pick it up within 5 s | `UNKNOWN host-did-not-run` (no retry) |

`IMG <id> <imageid>` exists in the source as a placeholder for a native image read; it is not
part of any verified result and is left in place for the next round.

## Build

No Visual Studio and no Windows SDK required — clang-cl plus import libraries synthesised from
`.def` files.

```powershell
powershell -ExecutionPolicy Bypass -File build_nb.ps1
```

Expected artefacts: `nb_probe.dll` (~13 KB, 9 exports, imports only from kernel32 and user32).

Under Git Bash, set `MSYS2_ARG_CONV_EXCL='*'` first, otherwise `/c`, `/Fo` get rewritten into paths.

## Run

```bat
copy nb_probe.dll C:\ProgramData\Gatan\Plugins\
start "" "C:\Program Files\Gatan\DigitalMicrograph.exe"
python nb_client.py ping 10
```

`nb_busy_test.py` brackets a 10-second Python script (`ExecutePythonScriptFile`) and sends
requests before, during and after it.

## Clean up

```bat
del C:\ProgramData\Gatan\Plugins\nb_probe.dll
del C:\ProgramData\Gatan\Plugins\nb_probe.log
```

The plugin dir is empty on a stock install; deleting the DLL restores that state. No registry
keys, no configuration, no service.

## Boundaries

- No vendor binaries, decompiled output, addresses or offsets are shipped here.
- One build only (3.53.4137 x64). Nothing here is a compatibility claim.
- The plugin deliberately keeps no state worth preserving: if it crashes, delete it and nothing
  is left behind.
- Do not load this into a session with unsaved work.
