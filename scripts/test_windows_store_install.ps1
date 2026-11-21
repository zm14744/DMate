param(
    [Parameter(Mandatory=$true)][string]$Directory,
    [Parameter(Mandatory=$true)][string]$Publisher,
    [Parameter(Mandatory=$true)][hashtable[]]$Packages
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:DMATE_STORE_SMOKE_RUNNER -ne 'github-hosted' -or
    $env:GITHUB_REPOSITORY -ne 'zm14744/DMate' -or $env:GITHUB_REF -ne 'refs/heads/main') {
    throw 'Store installation smoke tests are restricted to this repository on an isolated GitHub-hosted main-branch Windows runner'
}
if ($PSVersionTable.PSEdition -ne 'Desktop') { throw 'Run the installation smoke test with Windows PowerShell and its native Appx module' }
$identity = 'DMate.DMate'
if (@(Get-AppxPackage -AllUsers -Name $identity).Count -ne 0) {
    throw 'An existing installation was found; it will not be changed or removed by this test'
}
$ordered = @($Packages | Sort-Object { [version]$_.Version })
if ($ordered.Count -lt 2 -or @($ordered.Version | Select-Object -Unique).Count -ne $ordered.Count) {
    throw 'The installation and upgrade smoke requires distinct, increasing package versions'
}
$reportPath = Join-Path $Directory 'DMate-Microsoft-Store-verification.json'
$report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
if ($report.status -ne 'package_integrity_passed' -or $report.build_commit -ne $env:GITHUB_SHA -or
    [string]$report.build_run_id -ne $env:GITHUB_RUN_ID) {
    throw 'Smoke testing requires the verified packages built by this workflow run'
}

# Activate the installed AUMID rather than launching a loose executable.
# This is the same activation contract used by the Windows certification kit.
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace DMateStoreSmoke {
    [ComImport, Guid("2E941141-7F97-4756-BA1D-9DECDE894A3D"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IActivationManager {
        [PreserveSig] int ActivateApplication([MarshalAs(UnmanagedType.LPWStr)] string id,
            [MarshalAs(UnmanagedType.LPWStr)] string arguments, uint options, out uint processId);
    }
    public static class Activation {
        public static uint Start(string id) {
            object instance = Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("45BA127D-10A8-46EA-8AB7-56EA9078943C")));
            try {
                uint processId;
                int result = ((IActivationManager)instance).ActivateApplication(id, null, 2, out processId);
                Marshal.ThrowExceptionForHR(result);
                return processId;
            } finally { Marshal.FinalReleaseComObject(instance); }
        }
    }
}
'@

$smokeStarted = [DateTime]::UtcNow
$ownedRoots = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
$addedCertificates = New-Object 'System.Collections.Generic.List[string]'
$results = New-Object 'System.Collections.Generic.List[object]'
$cleanupErrors = New-Object 'System.Collections.Generic.List[string]'
$temporary = Join-Path $env:RUNNER_TEMP ('dmate-store-smoke-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporary | Out-Null
$attemptedInstall = $false
$smokeError = $null

function Get-OwnedProcesses([string]$Root) {
    $prefix = $Root.TrimEnd('\') + '\'
    foreach ($process in @(Get-Process -Name DMateLauncher,dmate-desktop,msedgewebview2 -ErrorAction SilentlyContinue)) {
        try {
            if ($process.Path -and $process.Path.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase) -and
                $process.StartTime.ToUniversalTime() -ge $smokeStarted) { $process }
        } catch { continue }
    }
}

function Stop-OwnedProcesses([string]$Root) {
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    do {
        $owned = @(Get-OwnedProcesses $Root)
        if ($owned.Count -eq 0) { return }
        foreach ($process in $owned) {
            $current = Get-Process -Id $process.Id -ErrorAction SilentlyContinue
            if ($current) {
                try {
                    if ($current.StartTime -eq $process.StartTime -and $current.Path -eq $process.Path) {
                        Stop-Process -InputObject $current -Force -ErrorAction Stop
                        [void]$current.WaitForExit(5000)
                    }
                } catch { if (-not $current.HasExited) { throw } }
            }
        }
    } while ([DateTime]::UtcNow -lt $deadline)
    if (@(Get-OwnedProcesses $Root).Count -gt 0) { throw 'A smoke-test process did not exit' }
}

try {
    foreach ($package in $ordered) {
        foreach ($root in $ownedRoots) { Stop-OwnedProcesses $root }
        $bundle = Join-Path $Directory $package.Bundle
        $record = @($report.files | Where-Object name -EQ $package.Bundle)
        if ($record.Count -ne 1 -or (Get-FileHash -LiteralPath $bundle -Algorithm SHA256).Hash.ToLowerInvariant() -ne $record[0].sha256) {
            throw 'The installation input no longer matches its verified artifact'
        }
        $signature = Get-AuthenticodeSignature -LiteralPath $bundle
        $certificate = $signature.SignerCertificate
        if (-not $certificate -or $certificate.Subject -cne $Publisher) { throw 'The bundle signing certificate does not match the configured publisher' }
        $certificatePath = "Cert:/LocalMachine/Root/$($certificate.Thumbprint)"
        if (-not (Test-Path -LiteralPath $certificatePath)) {
            $certificateFile = Join-Path $temporary ($certificate.Thumbprint + '.cer')
            [IO.File]::WriteAllBytes($certificateFile,$certificate.Export([Security.Cryptography.X509Certificates.X509ContentType]::Cert))
            Import-Certificate -FilePath $certificateFile -CertStoreLocation 'Cert:/LocalMachine/Root' | Out-Null
            $addedCertificates.Add($certificatePath)
        }
        if ((Get-AuthenticodeSignature -LiteralPath $bundle).Status -ne 'Valid') { throw 'The trusted bundle signature is invalid' }

        $attemptedInstall = $true
        Add-AppxPackage -Path $bundle -ErrorAction Stop
        $installed = @(Get-AppxPackage -Name $identity | Where-Object { $_.Publisher -ceq $Publisher })
        if ($installed.Count -ne 1 -or [string]$installed[0].Version -ne $package.Version) { throw 'The installed package is not the requested version' }
        $installed = $installed[0]
        [void]$ownedRoots.Add($installed.InstallLocation)
        [xml]$manifest = Get-Content -LiteralPath (Join-Path $installed.InstallLocation 'AppxManifest.xml') -Raw
        $applications = @($manifest.Package.Applications.Application)
        if ($applications.Count -ne 1 -or $applications[0].Executable -cne 'DMateLauncher.exe') { throw 'Unexpected installed application entry point' }
        $aumid = $installed.PackageFamilyName + '!' + $applications[0].Id
        $activatedProcessId = [DMateStoreSmoke.Activation]::Start($aumid)
        if ($activatedProcessId -eq 0) { throw 'Windows activation did not return a process ID' }

        $deadline = [DateTime]::UtcNow.AddSeconds(60)
        $application = $null
        do {
            $processes = @(Get-OwnedProcesses $installed.InstallLocation)
            $application = $processes | Where-Object { $_.ProcessName -eq 'dmate-desktop' -and $_.MainWindowHandle -ne [IntPtr]::Zero } | Select-Object -First 1
            $runtime = @($processes | Where-Object ProcessName -EQ 'msedgewebview2')
            if ($application -and $runtime.Count -gt 0) { break }
            Start-Sleep -Milliseconds 500
        } while ([DateTime]::UtcNow -lt $deadline)
        if (-not $application -or $runtime.Count -eq 0) { throw 'The installed application did not open a window with its bundled WebView2 runtime' }

        $observedStart = [DateTime]::UtcNow
        do {
            $processes = @(Get-OwnedProcesses $installed.InstallLocation)
            $live = @($processes | Where-Object { $_.Id -eq $application.Id -and $_.StartTime -eq $application.StartTime -and $_.MainWindowHandle -ne [IntPtr]::Zero })
            if ($live.Count -ne 1 -or @($processes | Where-Object ProcessName -EQ 'msedgewebview2').Count -eq 0) {
                throw 'The installed application or its bundled runtime exited during the smoke observation'
            }
            Start-Sleep -Milliseconds 500
        } while (([DateTime]::UtcNow - $observedStart).TotalSeconds -lt 10)
        $results.Add(@{name=$package.Bundle; version=$package.Version; package_full_name=$installed.PackageFullName;
            aumid=$aumid; activation_process_id=$activatedProcessId; application_process_id=$application.Id;
            window_observed=$true; bundled_webview_observed=$true; observed_seconds=10})
        Write-Host "Installed and launched $($package.Bundle); application window and bundled WebView2 stayed alive for 10 seconds."
    }
} catch {
    $smokeError = $_
} finally {
    foreach ($root in $ownedRoots) {
        try { Stop-OwnedProcesses $root } catch { $cleanupErrors.Add('Could not stop an owned package process') }
    }
    if ($attemptedInstall) {
        try {
            foreach ($installed in @(Get-AppxPackage -Name $identity | Where-Object { $_.Publisher -ceq $Publisher -and [string]$_.Version -in $ordered.Version })) {
                Stop-OwnedProcesses $installed.InstallLocation
                Remove-AppxPackage -Package $installed.PackageFullName -ErrorAction Stop
            }
        } catch { $cleanupErrors.Add('Could not remove the smoke-test package') }
    }
    foreach ($certificatePath in $addedCertificates) {
        try { Remove-Item -LiteralPath $certificatePath -Force -ErrorAction Stop } catch { $cleanupErrors.Add('Could not remove a smoke-test certificate') }
    }
    try { Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction Stop } catch { $cleanupErrors.Add('Could not remove the smoke-test temporary directory') }
    $passed = -not $smokeError -and $cleanupErrors.Count -eq 0 -and $results.Count -eq $ordered.Count
    $report.installation_test = if ($passed) { 'passed' } else { 'failed' }
    $report.upgrade_test = if ($passed) { 'passed' } else { 'failed' }
    $report | Add-Member -NotePropertyName install_smoke -NotePropertyValue @{
        status=$(if ($passed) { 'passed' } else { 'failed' });
        cleanup=$(if ($cleanupErrors.Count -eq 0) { 'passed' } else { 'failed' });
        runner='github-hosted'; os_version=[Environment]::OSVersion.VersionString;
        packages=@($results.ToArray()); scope='Package installation, AUMID launch and increasing-version upgrade only'
    } -Force
    [IO.File]::WriteAllText($reportPath,($report | ConvertTo-Json -Depth 10),[Text.UTF8Encoding]::new($false))
}
if ($smokeError) { throw $smokeError }
if ($cleanupErrors.Count -gt 0) { throw ($cleanupErrors -join '; ') }
if (-not $passed) { throw 'Store installation smoke testing did not complete' }
Write-Host 'Package installation, launch and upgrade smoke passed; WACK, business behavior and user-data migration remain untested.'
