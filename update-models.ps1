$ErrorActionPreference = 'Stop'
if (Get-Command python -ErrorAction SilentlyContinue) {
    & python "$PSScriptRoot/scripts/nd.py" --root "$PSScriptRoot" models update @args
} else {
    & py -3 "$PSScriptRoot/scripts/nd.py" --root "$PSScriptRoot" models update @args
}
exit $LASTEXITCODE
