$ErrorActionPreference = 'Stop'
$TaskRoot = $PSScriptRoot
if (Get-Command python -ErrorAction SilentlyContinue) {
    & python "$TaskRoot/scripts/nd.py" --root "$TaskRoot" install @args
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 "$TaskRoot/scripts/nd.py" --root "$TaskRoot" install @args
} else {
    throw 'Python 3.10+ is required: https://www.python.org/downloads/'
}
exit $LASTEXITCODE
