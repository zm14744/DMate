param([switch]$PublishOnly)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest

$repository = 'zm14744/DMate'
$releaseTag = 'v1.0.1'
$repoRoot = Split-Path -Parent $PSScriptRoot
$outputRoot = Join-Path $repoRoot 'dist/windows-store'
$sourceName = 'DMate_1.0.2_x64-setup.exe'
$sourceHash = '85aae11548c72174474523175a42f648e36c91f195a8ec72529fb047723fcbfb'
$appHash = '90c5bd197f5622afa2982c8341ee658125eddfc19453fa0dbfe525954cff167d'
$publisher = 'CN=F4B4F5DD-9B90-49AA-A3A9-C0B049718711'
$runtimeVersion = '157.0.4341.42'
$runtimeName = "Microsoft.WebView2.FixedVersionRuntime.$runtimeVersion.x64.cab"
$runtimeUrl = "https://msedge.sf.dl.delivery.mp.microsoft.com/filestreamingservice/files/b7b22a57-b321-483e-9855-d260b076f1a7/$runtimeName"

function Run-Checked([string]$Program, [string[]]$Arguments) {
    Write-Host "Running $(Split-Path -Leaf $Program)"
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Tool failed: $Program (exit $LASTEXITCODE)" }
}
function Require-Hash([string]$Path, [string]$Expected) {
    if ((Get-FileHash $Path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Expected) {
        throw "Unexpected SHA256 for $(Split-Path -Leaf $Path)"
    }
}

if ($PublishOnly) {
    $report = Get-Content (Join-Path $outputRoot 'DMate-Microsoft-Store-verification.json') -Raw | ConvertFrom-Json
    if ($report.status -ne 'passed') { throw 'Store package verification did not pass' }
    $release = (& gh release view $releaseTag --repo $repository --json assets,body | ConvertFrom-Json)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read GitHub Release' }
    $alreadyPublished = @($release.assets | ForEach-Object { $_.name })
    foreach ($item in $report.files) {
        $path = Join-Path $outputRoot $item.name
        Require-Hash $path $item.sha256
    }
    foreach ($file in Get-ChildItem $outputRoot -File) {
        if ($alreadyPublished -contains $file.Name) {
            throw "Release asset already exists; keep the published version intact: $($file.Name)"
        }
    }
    foreach ($file in Get-ChildItem $outputRoot -File) {
        Run-Checked 'gh' @('release','upload',$releaseTag,$file.FullName,'--repo',$repository)
    }
    $verifyRoot = Join-Path $env:RUNNER_TEMP 'dmate-store-published-verification'
    New-Item -ItemType Directory -Force $verifyRoot | Out-Null
    foreach ($item in $report.files) {
        Run-Checked 'gh' @('release','download',$releaseTag,'--repo',$repository,'--pattern',$item.name,'--dir',$verifyRoot)
        Require-Hash (Join-Path $verifyRoot $item.name) $item.sha256
    }
    $notes = [string]$release.body
    $notes += @"


### Microsoft Store submission packages

- ``DMate_1.0.3.0.msixbundle``: modern desktop package, Windows 10 build 19041 or later.
- ``DMate_1.0.2.0.classic.appxbundle``: desktop fallback, Windows 10 build 17763 or later.

Both contain the same latest Windows application 1.0.2 x64 and the bundled Microsoft WebView2 runtime. The distinct Store package versions preserve the primary/fallback order. Identity: ``DMate.DMate``; publisher: ``$publisher``. These files are for the existing DMate Partner Center product; Microsoft submission is performed separately by the owner. Select **Windows 10/11 Desktop**. See ``DMate-Microsoft-Store-README.txt`` and the Store-specific checksum file for details.
"@
    $notesFile = Join-Path $env:RUNNER_TEMP 'dmate-store-release-notes.md'
    [IO.File]::WriteAllText($notesFile, $notes, [Text.UTF8Encoding]::new($false))
    Run-Checked 'gh' @('release','edit',$releaseTag,'--repo',$repository,'--notes-file',$notesFile)
    Write-Host 'Verified Store submission files are published to GitHub Release.'
    exit 0
}

$work = Join-Path $env:RUNNER_TEMP 'dmate-store-build'
$downloadRoot = Join-Path $work 'downloads'
New-Item -ItemType Directory -Force $downloadRoot,$outputRoot | Out-Null
Run-Checked 'gh' @('release','download',$releaseTag,'--repo',$repository,'--pattern',$sourceName,'--dir',$downloadRoot)
$installer = Join-Path $downloadRoot $sourceName
Require-Hash $installer $sourceHash
$extractRoot = Join-Path $work 'installer'
Run-Checked 'C:/Program Files/7-Zip/7z.exe' @('x',$installer,"-o$extractRoot",'-y')
$executables = @(Get-ChildItem $extractRoot -Recurse -Filter 'dmate-desktop.exe' -File)
if ($executables.Count -ne 1) { throw 'Expected one actual DMate desktop executable' }
$appExe = $executables[0].FullName
Require-Hash $appExe $appHash
$version = (Get-Item $appExe).VersionInfo
if ($version.FileMajorPart -ne 1 -or $version.FileMinorPart -ne 0 -or $version.FileBuildPart -ne 2) {
    throw 'The published application is not version 1.0.2'
}

$runtimeCache = Join-Path $env:RUNNER_TEMP 'dmate-store-runtime-cache'
New-Item -ItemType Directory -Force $runtimeCache | Out-Null
$cab = Join-Path $runtimeCache $runtimeName
if (-not (Test-Path $cab)) {
    Write-Host 'Downloading the official fixed WebView2 runtime'
    Invoke-WebRequest -Uri $runtimeUrl -OutFile $cab -MaximumRetryCount 2 -RetryIntervalSec 3 -TimeoutSec 900
}
$runtimeExtract = Join-Path $work 'runtime'
New-Item -ItemType Directory -Force $runtimeExtract | Out-Null
Run-Checked 'expand.exe' @($cab,'-F:*',$runtimeExtract)
$runtimeExecutables = @(Get-ChildItem $runtimeExtract -Recurse -Filter 'msedgewebview2.exe' -File)
if ($runtimeExecutables.Count -ne 1) { throw 'Official fixed WebView2 runtime was not extracted correctly' }
$runtimeExe = $runtimeExecutables[0]
$runtimeSignature = Get-AuthenticodeSignature $runtimeExe.FullName
if ($runtimeSignature.Status -ne 'Valid' -or $runtimeSignature.SignerCertificate.Subject -notmatch 'Microsoft Corporation') {
    throw 'The bundled Microsoft WebView2 executable signature is not valid'
}

$sdkRoot = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits/10/bin'
$sdk = Get-ChildItem $sdkRoot -Directory | Where-Object Name -Match '^10\.0\.\d+\.0$' |
    Sort-Object { [version]$_.Name } -Descending | Select-Object -First 1
if (-not $sdk) { throw 'Windows SDK is not installed' }
$sdkBin = Join-Path $sdk.FullName 'x64'
$makeAppx = Join-Path $sdkBin 'makeappx.exe'
$makePri = Join-Path $sdkBin 'makepri.exe'
$signTool = Join-Path $sdkBin 'signtool.exe'
$rc = Join-Path $sdkBin 'rc.exe'
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
$vsRoot = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if ($LASTEXITCODE -ne 0 -or -not $vsRoot) { throw 'MSVC compiler is not installed' }
$devCmd = Join-Path $vsRoot 'Common7/Tools/VsDevCmd.bat'
$launcher = Join-Path $work 'DMateLauncher.exe'
$resourceSource = Join-Path $work 'launcher.rc'
$resource = Join-Path $work 'launcher.res'
$icon = (Join-Path $repoRoot 'desktop/src-tauri/icons/icon.ico').Replace('\','/')
Set-Content -LiteralPath $resourceSource -Value "1 ICON `"$icon`"" -Encoding ascii
Run-Checked $rc @('/nologo','/fo',$resource,$resourceSource)
$launcherSource = Join-Path $repoRoot 'desktop/windows-store/launcher.cpp'
$compile = 'call "{0}" -no_logo -arch=x64 -host_arch=x64 && cl.exe /nologo /utf-8 /std:c++17 /O2 /MT /EHsc /DUNICODE /D_UNICODE "{1}" "{2}" /Fe:"{3}" /link /SUBSYSTEM:WINDOWS /MACHINE:X64 user32.lib shell32.lib' -f $devCmd,$launcherSource,$resource,$launcher
Run-Checked 'cmd.exe' @('/d','/s','/c',$compile)

$layouts = Join-Path $work 'layouts'
Run-Checked 'python' @((Join-Path $PSScriptRoot 'prepare_windows_store.py'),'--exe',$appExe,'--launcher',$launcher,'--runtime',$runtimeExe.DirectoryName,'--output',$layouts)
$priConfig = Join-Path $work 'priconfig.xml'
Run-Checked $makePri @('createconfig','/cf',$priConfig,'/dq','en-US','/pv','10.0.0','/o')
[xml]$pri = Get-Content $priConfig -Raw
foreach ($index in $pri.SelectNodes('//index')) { $index.SetAttribute('startIndexAt','Assets') }
foreach ($packaging in @($pri.SelectNodes('//packaging'))) { [void]$packaging.ParentNode.RemoveChild($packaging) }
$pri.Save($priConfig)

$packages = @(
    @{ Layout='modern'; Version='1.0.3.0'; Extension='msix'; Bundle='DMate_1.0.3.0.msixbundle' },
    @{ Layout='classic'; Version='1.0.2.0'; Extension='appx'; Bundle='DMate_1.0.2.0.classic.appxbundle' }
)
$certificate = New-SelfSignedCertificate -Type Custom -Subject $publisher -KeyUsage DigitalSignature `
    -FriendlyName 'DMate Store Submission' -CertStoreLocation 'Cert:/CurrentUser/My' `
    -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.3','2.5.29.19={text}')
$certificatePassword = [Guid]::NewGuid().ToString('N')
Write-Output "::add-mask::$certificatePassword"
$pfx = Join-Path $work 'submission-signing.pfx'
$cer = Join-Path $work 'submission-signing.cer'
Export-PfxCertificate -Cert $certificate -FilePath $pfx -Password (ConvertTo-SecureString $certificatePassword -AsPlainText -Force) | Out-Null
Export-Certificate -Cert $certificate -FilePath $cer | Out-Null
Run-Checked 'certutil.exe' @('-f','-addstore','Root',$cer)
$records = @()
foreach ($package in $packages) {
    $layout = Join-Path $layouts $package.Layout
    $manifest = Join-Path $layout 'AppxManifest.xml'
    [xml]$xml = Get-Content $manifest -Raw
    if ($xml.Package.Identity.Name -ne 'DMate.DMate' -or $xml.Package.Identity.Publisher -ne $publisher -or $xml.Package.Identity.Version -ne $package.Version) {
        throw 'The Store identity or package version does not match the approved product'
    }
    Run-Checked $makePri @('new','/pr',$layout,'/cf',$priConfig,'/mn',$manifest,'/of',(Join-Path $layout 'resources.pri'),'/o')
    $innerRoot = Join-Path $work "packages/$($package.Layout)"
    New-Item -ItemType Directory -Force $innerRoot | Out-Null
    $inner = Join-Path $innerRoot "DMate_$($package.Version)_x64.$($package.Extension)"
    Run-Checked $makeAppx @('pack','/d',$layout,'/p',$inner,'/h','SHA256','/o')
    $bundle = Join-Path $outputRoot $package.Bundle
    Run-Checked $makeAppx @('bundle','/d',$innerRoot,'/p',$bundle,'/o')
    Run-Checked $signTool @('sign','/fd','SHA256','/f',$pfx,'/p',$certificatePassword,$bundle)
    Run-Checked $signTool @('verify','/pa',$bundle)
    $unbundle = Join-Path $work "verified/$($package.Layout)"
    Run-Checked $makeAppx @('unbundle','/p',$bundle,'/d',$unbundle,'/o')
    $innerName = Split-Path -Leaf $inner
    $unpack = Join-Path $work "verified-layout/$($package.Layout)"
    Run-Checked $makeAppx @('unpack','/p',(Join-Path $unbundle $innerName),'/d',$unpack,'/o')
    Require-Hash (Join-Path $unpack 'App/dmate-desktop.exe') $appHash
    [xml]$packedManifest = Get-Content (Join-Path $unpack 'AppxManifest.xml') -Raw
    if ($packedManifest.Package.Identity.Name -ne 'DMate.DMate' -or $packedManifest.Package.Identity.Publisher -ne $publisher -or $packedManifest.Package.Identity.Version -ne $package.Version) {
        throw 'Unpacked Store package identity does not match the source manifest'
    }
    Require-Hash (Join-Path $unpack 'App/WebView2/msedgewebview2.exe') ((Get-FileHash $runtimeExe.FullName -Algorithm SHA256).Hash.ToLowerInvariant())
    $expectedRuntimeFiles = @(Get-ChildItem $runtimeExe.DirectoryName -Recurse -File).Count
    if (@(Get-ChildItem (Join-Path $unpack 'App/WebView2') -Recurse -File).Count -ne $expectedRuntimeFiles) {
        throw 'The packaged WebView2 runtime is incomplete'
    }
    $records += @{name=$package.Bundle; sha256=(Get-FileHash $bundle -Algorithm SHA256).Hash.ToLowerInvariant(); bytes=(Get-Item $bundle).Length; package_version=$package.Version}
}
$readme = @"
DMate Microsoft Store submission packages

Source Windows application: 1.0.2 x64, taken from the verified latest DMate Windows installer.
Store identity: DMate.DMate
Publisher: $publisher
Publisher display name: DMate

DMate_1.0.3.0.msixbundle: modern package, Windows 10 build 19041 or later.
DMate_1.0.2.0.classic.appxbundle: fallback package, Windows 10 build 17763 or later.
Both include the SAME application 1.0.2 and Fixed WebView2 $runtimeVersion x64.
The distinct Store versions maintain the primary/fallback order shown in Partner Center.

Upload these two bundles to the existing DMate product in Partner Center. Select Windows 10/11 Desktop; the packaged desktop application does not declare Mixed Reality or Mobile support.
The files use a temporary, matching-publisher submission signature. Microsoft re-signs accepted Store packages. No private key or local-installation certificate is distributed.
If Partner Center requests a runFullTrust explanation: DMate uses a standard desktop process to display its WebView2 interface; it does not request administrator rights.

Microsoft WebView2 Fixed Runtime source: $runtimeUrl
Original installer SHA256: $sourceHash
Original application SHA256: $appHash
"@
$readmeFile = Join-Path $outputRoot 'DMate-Microsoft-Store-README.txt'
[IO.File]::WriteAllText($readmeFile,$readme,[Text.UTF8Encoding]::new($false))
$sums = ($records | ForEach-Object { "$($_.sha256)  $($_.name)" }) -join "`n"
$sumsFile = Join-Path $outputRoot 'DMate-Microsoft-Store-SHA256SUMS.txt'
[IO.File]::WriteAllText($sumsFile,$sums+"`n",[Text.UTF8Encoding]::new($false))
foreach ($file in @($readmeFile,$sumsFile)) {
    $records += @{name=(Split-Path -Leaf $file); sha256=(Get-FileHash $file -Algorithm SHA256).Hash.ToLowerInvariant(); bytes=(Get-Item $file).Length}
}
$report = @{status='passed'; source_version='1.0.2'; source_installer_sha256=$sourceHash; source_executable_sha256=$appHash; publisher=$publisher; runtime_version=$runtimeVersion; signature='self-signed for Store submission; Store re-signing required'; files=$records}
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $outputRoot 'DMate-Microsoft-Store-verification.json') -Encoding utf8
Remove-Item $pfx,$cer -Force
Write-Host 'Both Store submission bundles were built, signed and unpacked for verification.'
