# PS010 — Cross-platform manifest

Repair `build-manifest.ps1`. The exact same submitted file will run under PowerShell 7.6.4 on Windows and in an isolated Linux PowerShell 7.6.4 container.

```powershell
build-manifest.ps1 -Root <fixture tree> -OutputPath <manifest.json> -ToolPath <platform helper>
```

Invoke the supplied native helper as `--root <Root>`; it prints one relative file path per line in platform-native syntax. Do not discover files independently. For every listed file, emit an object with `path` and `bytes`. Normalize path separators to `/`, sort paths using ordinal comparison, and serialize one compact JSON array. Write UTF-8 without BOM followed by exactly one LF, creating the output directory when needed.

The current working directory will not be the script directory, the helper is not on `PATH`, and fixtures contain spaces, parentheses, Unicode, and deep paths. Repeated runs and both operating systems must produce byte-identical output. Do not modify the helpers or fixtures.
