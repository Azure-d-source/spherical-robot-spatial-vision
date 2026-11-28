#requires -Version 7.0
[CmdletBinding()]
param(
    [string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$commit = git -C $repo rev-parse --verify HEAD
if ($LASTEXITCODE -ne 0) { throw '无法确定要导出的 Git 提交。' }

if (!$OutputDirectory) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $OutputDirectory = Join-Path $repo "outputs/splatforge-anonymous-$stamp"
}
$destination = [IO.Path]::TrimEndingDirectorySeparator(
    [IO.Path]::GetFullPath($OutputDirectory, (Get-Location).ProviderPath)
)
if (Test-Path -LiteralPath $destination) { throw "导出目录已存在：$destination" }

$excluded = @(
    '.git', 'local', 'data', 'node_modules', '.venv', 'venv', 'dist', 'target',
    '__pycache__', '.pytest_cache', 'artifacts', 'runs', 'outputs', 'checkpoints'
) | ForEach-Object { ":(exclude,glob)**/$_/**" }
$excluded += @(
    ':(exclude,glob)**/.env'
    ':(exclude,glob)**/.env.*'
    ':(exclude,top)docs/competition/submission-checklist.md'
    ':(exclude,top)docs/research/4c-award-review.md'
    ':(exclude,top)scripts/export-anonymous-submission.ps1'
)

# Rewrite the known examples only. The scan rejects any other local path or identity.
$edits = @{
    'README.md' = [ordered]@{
        ' · [数据组织](data/README.md)' = ''
        ' · [参赛与交付清单](docs/competition/submission-checklist.md)' = ''
    }
    'docs/design/project-overview.md' = [ordered]@{
        '- [参赛与交付清单](../competition/submission-checklist.md)记录赛事原通知要求与当前证据项。' = ''
        '与[4C 人工智能应用国奖作品调研](../research/4c-award-review.md)记录技术路线与竞赛案例。' = '记录技术路线。'
    }
    'docs/design/execution-plan.md' = [ordered]@{
        ' · [交付清单](../competition/submission-checklist.md)' = ''
    }
    'docs/research/spatial-vision-research.md' = [ordered]@{
        '案例借鉴与获奖证据见 [4C 人工智能应用国奖作品调研](4c-award-review.md)。' = ''
    }
    'docs/experiments/workbench-gpu-smoke.md' = [ordered]@{
        'D:\orbitforge-smoke\' = '.\gpu-smoke\'
    }
    'src/README.md' = [ordered]@{
        'D:/vision-tools/' = './vision-tools/'
        'D:\vision-tools\' = '.\vision-tools\'
        'D:\vision-models\' = '.\vision-models\'
    }
    'src/api/platform/README.md' = [ordered]@{
        'C:\Tools\cloudflared.exe' = '.\tools\cloudflared.exe'
    }
    'docs/deployment/cloudflared.orbit.example.yml' = [ordered]@{
        'C:/Users/<WINDOWS_USER>/.cloudflared/<TUNNEL_UUID>.json' = '<CLOUDFLARED_CREDENTIALS_FILE>'
    }
}
$teamAccount = 'Azure-d-source'
$teamUrl = 'https?://(?:www\.)?github\.com/' + [regex]::Escape($teamAccount) + '(?![\w-])(?:/[^\s)<>\]]*)?'
$forbidden = [ordered]@{
    '学院名称' = '河南师范大学|软件学院'
    '年级' = '\p{Nd}{4}\s*[级級]'
    '团队标识' = [regex]::Escape($teamAccount) + '|spherical-robot-spatial-vision'
    '本机绝对盘符' = '(?<![a-z0-9_])[a-z]:[\\/]'
}
$utf8 = [Text.UTF8Encoding]::new($false, $true)

$parent = [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($destination)).FullName
$parent = (Resolve-Path -LiteralPath $parent).ProviderPath
$scratch = Join-Path $parent ('.splatforge-export-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $scratch | Out-Null
try {
    $archive = Join-Path $scratch 'source.zip'
    $staged = Join-Path $scratch 'source'
    git -C $repo archive --format=zip --output $archive $commit -- . @excluded
    if ($LASTEXITCODE -ne 0) { throw 'Git 源码归档失败。' }
    Expand-Archive -LiteralPath $archive -DestinationPath $staged

    $files = @(Get-ChildItem -LiteralPath $staged -Force -Recurse -File)
    foreach ($file in $files) {
        $relative = [IO.Path]::GetRelativePath($staged, $file.FullName).Replace('\', '/')
        try {
            $original = [IO.File]::ReadAllText($file.FullName, $utf8)
        } catch {
            throw "无法读取并校验导出文件：$relative"
        }
        if ($original.Contains([char]0)) { throw "导出文件不是可校验的文本：$relative" }

        $content = $original
        if ($edits.ContainsKey($relative)) {
            foreach ($example in $edits[$relative].GetEnumerator()) {
                $content = $content.Replace($example.Key, $example.Value)
            }
        }
        if ($relative -eq 'README.md') {
            $content = $content -replace '(?ms)^### 匿名源码导出\r?\n.*?^\x60{3}[ \t]*(?:\r?\n|\z)', ''
        }
        $content = $content -replace "\[([^\]\r\n]+)\]\($teamUrl\)", '$1（地址已省略）'
        $content = $content -replace $teamUrl, '（团队仓库地址已省略）'
        if ($content -cne $original) { [IO.File]::WriteAllText($file.FullName, $content, $utf8) }

        foreach ($rule in $forbidden.GetEnumerator()) {
            if ($relative -match $rule.Value) { throw "匿名校验失败（$($rule.Key)）：导出文件名" }
            if ($content -match $rule.Value) {
                throw "匿名校验失败（$($rule.Key)）：$relative"
            }
        }
    }

    [IO.Directory]::Move($staged, $destination)
    Write-Host "匿名校验通过，共 $($files.Count) 个文件，来源提交 $($commit.Substring(0, 7))。"
    Write-Output $destination
} finally {
    $resolvedScratch = (Resolve-Path -LiteralPath $scratch).ProviderPath
    if ($resolvedScratch -ne $scratch -or (Split-Path -Parent $resolvedScratch) -ne $parent) {
        throw '临时目录位置异常，已保留现场。'
    }
    Remove-Item -LiteralPath $resolvedScratch -Recurse -Force
}
