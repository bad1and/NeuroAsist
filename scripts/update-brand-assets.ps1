[CmdletBinding()]
param(
    [string]$Source,
    [switch]$SkipIcons
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$brand = Join-Path $root "apps\web\public\brand"
$icons = Join-Path $root "apps\desktop\src-tauri\icons"
$canonical = Join-Path $brand "iris-logo.svg"
$utf8 = New-Object System.Text.UTF8Encoding($false)

if ($Source) {
    $sourcePath = (Resolve-Path -LiteralPath $Source).Path
    if ($sourcePath -ne $canonical) {
        [IO.File]::WriteAllText($canonical, [IO.File]::ReadAllText($sourcePath), $utf8)
    }
}

[xml]$logo = [IO.File]::ReadAllText($canonical)
$ns = New-Object System.Xml.XmlNamespaceManager($logo.NameTable)
$ns.AddNamespace("s", "http://www.w3.org/2000/svg")
$shapes = $logo.SelectSingleNode("/s:svg/s:g/s:g", $ns)
$mainPaths = @($shapes.SelectNodes("s:path", $ns))
if ($logo.DocumentElement.GetAttribute("viewBox") -ne "0 0 344 144" -or $mainPaths.Count -ne 8) {
    throw "Expected the Iris V3 SVG with eight contours and viewBox 0 0 344 144."
}

# Share the original petal geometry/palette with the lightweight Anime.js loader.
$petals = @(foreach ($index in @(0, 6, 7)) {
    $gradient = $logo.SelectSingleNode("/s:svg/s:defs/s:linearGradient[@id='paint${index}_linear_118_271']", $ns)
    [ordered]@{
        d = $mainPaths[$index].GetAttribute("d")
        x1 = $gradient.GetAttribute("x1"); y1 = $gradient.GetAttribute("y1")
        x2 = $gradient.GetAttribute("x2"); y2 = $gradient.GetAttribute("y2")
        stops = @($gradient.ChildNodes | ForEach-Object {
            [ordered]@{
                offset = $(if ($_.HasAttribute("offset")) { $_.GetAttribute("offset") } else { "0" })
                color = $_.GetAttribute("stop-color")
            }
        })
    }
})
$petalJson = ConvertTo-Json -InputObject $petals -Depth 5
[IO.File]::WriteAllText((Join-Path $root "apps\web\src\brand\iris-petals.json"), $petalJson + "`n", $utf8)
# Lettering stays vector artwork: retain the supplied Iris letterforms exactly.
$lettering = @(foreach ($index in @(1, 4, 5, 2, 3)) {
    $gradient = $logo.SelectSingleNode("/s:svg/s:defs/s:linearGradient[@id='paint${index}_linear_118_271']", $ns)
    [ordered]@{
        d = $mainPaths[$index].GetAttribute("d")
        letter = $(switch ($index) { 1 { 0 }; 4 { 1 }; 5 { 2 }; 2 { 2 }; 3 { 3 } })
        x1 = $gradient.GetAttribute("x1"); y1 = $gradient.GetAttribute("y1")
        x2 = $gradient.GetAttribute("x2"); y2 = $gradient.GetAttribute("y2")
        stops = @($gradient.ChildNodes | ForEach-Object {
            [ordered]@{
                offset = $(if ($_.HasAttribute("offset")) { $_.GetAttribute("offset") } else { "0" })
                color = $_.GetAttribute("stop-color")
            }
        })
    }
})
[IO.File]::WriteAllText((Join-Path $root "apps\web\src\brand\iris-lettering.json"),
    (ConvertTo-Json -InputObject $lettering -Depth 5) + "`n", $utf8)
$seedGradients = ($logo.SelectNodes('/s:svg/s:defs/s:linearGradient', $ns) | ForEach-Object { $_.OuterXml }) -join ''
$seedLetters = (@(1, 2, 3, 4, 5) | ForEach-Object { $mainPaths[$_].OuterXml }) -join ''
$seed = '<svg viewBox="0 0 344 144" fill="none" xmlns="http://www.w3.org/2000/svg"><defs>' +
    $seedGradients + '</defs><g opacity="0.25" transform="translate(76 120) scale(0.1 0.38) translate(-76 -120)">' +
    $mainPaths[0].OuterXml + '</g><g opacity="0.18">' + $seedLetters + '</g></svg>'
[IO.File]::WriteAllText((Join-Path $brand "iris-startup-seed.svg"), $seed + "`n", $utf8)

function Save-Svg([xml]$Document, [string]$Path) {
    $settings = New-Object System.Xml.XmlWriterSettings
    $settings.Encoding = $utf8
    $settings.Indent = $true
    $settings.OmitXmlDeclaration = $true
    $settings.NewLineChars = "`n"
    $writer = [System.Xml.XmlWriter]::Create($Path, $settings)
    try { $Document.Save($writer) } finally { $writer.Dispose() }
    [IO.File]::AppendAllText($Path, "`n", $utf8)
}

# Keep all original contours, gradients, masks and subtle static shadows.
# Both theme aliases use the supplied palette without recoloring it.
foreach ($theme in @("light", "dark")) {
    Save-Svg $logo (Join-Path $brand "iris-wordmark-$theme.svg")
}

[xml]$mark = $logo.CloneNode($true)
$markNs = New-Object System.Xml.XmlNamespaceManager($mark.NameTable)
$markNs.AddNamespace("s", "http://www.w3.org/2000/svg")
$markShapes = $mark.SelectSingleNode("/s:svg/s:g/s:g", $markNs)
$pathGroups = @($markShapes) + @($markShapes.SelectNodes("s:g", $markNs))
foreach ($group in $pathGroups) {
    $paths = @($group.SelectNodes("s:path", $markNs))
    if ($paths.Count -ne 8) { throw "Expected eight contours in each SVG layer." }
    # V3: top petal, I, i dot, s, r, i stem, left petal, right petal.
    foreach ($index in @(1, 2, 3, 4, 5)) {
        [void]$group.RemoveChild($paths[$index])
    }
}
$mark.DocumentElement.SetAttribute("viewBox", "0 -4 152 152")
$mark.DocumentElement.SetAttribute("width", "116")
$mark.DocumentElement.SetAttribute("height", "116")
foreach ($theme in @("light", "dark")) {
    Save-Svg $mark (Join-Path $brand "iris-mark-$theme.svg")
}

# The backing already fills the canvas. Keep its complete rounded silhouette
# and enlarge the mark to the full inner viewport without clipping the petals.
# All operating-system icon sizes are rendered from this SVG.
[xml]$backed = '<svg width="116" height="116" viewBox="0 0 116 116" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M0 54C0 28.5442 0 15.8162 7.90812 7.90812C15.8162 0 28.5442 0 54 0H90C102.257 0 108.385 0 112.192 3.80761C116 7.61522 116 13.7435 116 26V62C116 87.4558 116 100.184 108.092 108.092C100.184 116 87.4558 116 62 116H26C13.7435 116 7.61522 116 3.80761 112.192C0 108.385 0 102.257 0 90V54Z" fill="#EEEEEE"/></svg>'
$inner = $backed.ImportNode($mark.DocumentElement, $true)
$inner.SetAttribute("x", "0")
$inner.SetAttribute("y", "0")
$inner.SetAttribute("width", "116")
$inner.SetAttribute("height", "116")
[void]$backed.DocumentElement.AppendChild($inner)
foreach ($theme in @("light", "dark")) {
    Save-Svg $backed (Join-Path $brand "iris-mark-backed-$theme.svg")
}
Save-Svg $backed (Join-Path $icons "icon.svg")

if (-not $SkipIcons) {
    $cli = Join-Path $root "apps\desktop\node_modules\.bin\tauri.cmd"
    if (-not (Test-Path -LiteralPath $cli)) { throw "Install apps/desktop dependencies to regenerate icons." }
    # Render away from watched resources, then replace complete files. Windows
    # scanners/builders can briefly map an icon while it is being regenerated.
    $stagingRoot = [IO.Path]::GetFullPath((Join-Path $root "build\brand-icons"))
    $staging = Join-Path $stagingRoot ([Guid]::NewGuid().ToString())
    [void][IO.Directory]::CreateDirectory($staging)
    & $cli icon (Join-Path $icons "icon.svg") --output $staging
    if ($LASTEXITCODE -ne 0) { throw "Tauri icon generation failed." }
    foreach ($file in Get-ChildItem -LiteralPath $staging -Recurse -File) {
        $relative = [IO.Path]::GetRelativePath($staging, $file.FullName)
        $destination = Join-Path $icons $relative
        [void][IO.Directory]::CreateDirectory((Split-Path -Parent $destination))
        for ($attempt = 0; ; $attempt++) {
            try {
                [IO.File]::Move($file.FullName, $destination, $true)
                break
            } catch [IO.IOException] {
                if ($attempt -ge 4) { throw }
                Start-Sleep -Milliseconds 200
            }
        }
    }
    foreach ($name in @("32x32.png", "64x64.png", "128x128.png", "128x128@2x.png", "icon.png", "icon.ico", "icon.icns")) {
        if (-not (Test-Path -LiteralPath (Join-Path $icons $name))) { throw "Tauri did not generate $name." }
    }
    $resolvedStaging = (Resolve-Path -LiteralPath $staging).Path
    if (-not $resolvedStaging.StartsWith($stagingRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Unexpected icon staging directory."
    }
    Remove-Item -LiteralPath $resolvedStaging -Recurse -Force
}

Write-Host "Updated Iris brand assets, animated petals, vector lettering and startup seed."
