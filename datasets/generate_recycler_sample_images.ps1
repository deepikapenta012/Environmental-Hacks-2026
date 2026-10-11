$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

function Draw-DocumentImage($Path, $Title, $Subtitle, $Details) {
  $bitmap = [System.Drawing.Bitmap]::new(1400, 990)
  $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
  $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
  $graphics.Clear([System.Drawing.Color]::FromArgb(246, 248, 251))
  $navy = [System.Drawing.Color]::FromArgb(24, 45, 74)
  $teal = [System.Drawing.Color]::FromArgb(0, 131, 120)
  $gray = [System.Drawing.Color]::FromArgb(76, 91, 110)
  $graphics.FillRectangle([System.Drawing.SolidBrush]::new([System.Drawing.Color]::White), 42, 42, 1316, 906)
  $graphics.FillRectangle([System.Drawing.SolidBrush]::new($navy), 42, 42, 1316, 166)
  $titleFont = [System.Drawing.Font]::new('Arial', 34, [System.Drawing.FontStyle]::Bold)
  $subtitleFont = [System.Drawing.Font]::new('Arial', 17, [System.Drawing.FontStyle]::Regular)
  $sectionFont = [System.Drawing.Font]::new('Arial', 16, [System.Drawing.FontStyle]::Bold)
  $bodyFont = [System.Drawing.Font]::new('Arial', 20, [System.Drawing.FontStyle]::Regular)
  $smallFont = [System.Drawing.Font]::new('Arial', 13, [System.Drawing.FontStyle]::Regular)
  $graphics.DrawString($Title, $titleFont, [System.Drawing.Brushes]::White, 82, 76)
  $graphics.DrawString($Subtitle, $subtitleFont, [System.Drawing.Brushes]::White, 84, 136)
  $graphics.FillRectangle([System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(232, 247, 244)), 82, 242, 1236, 54)
  $graphics.DrawString('SYNTHETIC DEMO EVIDENCE  |  NOT AN OFFICIAL WEIGHMENT OR CERTIFICATE', $sectionFont, [System.Drawing.SolidBrush]::new($teal), 100, 257)
  $y = 340
  foreach ($line in $Details) {
    $graphics.DrawString($line.Label, $sectionFont, [System.Drawing.SolidBrush]::new($gray), 94, $y)
    $graphics.DrawString([string]$line.Value, $bodyFont, [System.Drawing.SolidBrush]::new($navy), 430, $y - 3)
    $graphics.DrawLine([System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(224, 230, 236), 1), 92, $y + 44, 1308, $y + 44)
    $y += 78
  }
  $graphics.DrawString('Prepared solely for ChainGuard testcase demonstrations. All names, accounts, quantities and references are synthetic.', $smallFont, [System.Drawing.SolidBrush]::new($gray), 94, 892)
  $bitmap.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
  $graphics.Dispose(); $bitmap.Dispose()
  $titleFont.Dispose(); $subtitleFont.Dispose(); $sectionFont.Dispose(); $bodyFont.Dispose(); $smallFont.Dispose()
}

function Add-ManifestRow($Directory, $Filename, $Category) {
  $manifest = Join-Path $Directory 'evidence_manifest.csv'
  $rows = @(Import-Csv -LiteralPath $manifest)
  if ($rows.Count -and $rows[0].PSObject.Properties.Name -contains 'evidence_category') {
    if (-not ($rows | Where-Object filename -eq $Filename)) {
      $rows += [pscustomobject]@{ evidence_category = $Category; filename = $Filename; status = 'PRESENT' }
    }
  } else {
    if (-not ($rows | Where-Object original_filename -eq $Filename)) {
      $rows += [pscustomobject]@{ category = $Category; original_filename = $Filename; demo_copy = "evidence/$Filename"; evidence_status = 'ACTIVE' }
    }
  }
  $rows | Export-Csv -LiteralPath $manifest -NoTypeInformation -Encoding utf8
}

$sampleRoot = Join-Path (Split-Path $PSScriptRoot -Parent) 'sample'
$caseDirs = @(
  Get-ChildItem -LiteralPath (Join-Path $sampleRoot 'new_testcases') -Directory
  Get-ChildItem -LiteralPath (Join-Path $sampleRoot 'previous_live_claim_examples') -Directory
)
foreach ($directory in $caseDirs) {
  $claim = Import-Csv -LiteralPath (Join-Path $directory.FullName 'claim.csv') | Select-Object -First 1
  $manifest = @(Import-Csv -LiteralPath (Join-Path $directory.FullName 'evidence_manifest.csv'))
  $isNew = $manifest.Count -and ($manifest[0].PSObject.Properties.Name -contains 'evidence_category')
  $producer = if ($claim.producer_name) { $claim.producer_name } else { $claim.producer_name }
  $recycler = $claim.recycler_name
  $received = [double]$claim.received_weight_kg
  $recovered = if ($claim.recovered_material_measurement_kg) { [double]$claim.recovered_material_measurement_kg } else { [math]::Round($received * 0.72, 1) }
  $date = $claim.collection_date
  $reference = if ($claim.testcase_id) { $claim.testcase_id } else { $claim.claim_reference }
  $receiptDate = $date
  $processedOutput = [math]::Round($recovered + [math]::Max(0, $received - $recovered), 1)
  $residual = [math]::Round([math]::Max(0, $received - $recovered), 1)
  $processingDate = $date
  if ($claim.claim_reference) {
    $receiptDate = '2026-10-10'
    $processingDate = '2026-10-10'
    $storedProcessing = @{
      'EWC-2026-08604' = @(200, 160, 40)
      'EWC-2026-08605' = @(200, 160, 40)
      'EWC-2026-08606' = @(200, 160, 40)
      'EWC-2026-08607' = @(400, 360, 40)
    }
    if ($storedProcessing.ContainsKey($reference)) {
      $processedOutput = $storedProcessing[$reference][0]
      $recovered = $storedProcessing[$reference][1]
      $residual = $storedProcessing[$reference][2]
    }
  }
  $evidenceDir = Join-Path $directory.FullName 'evidence'
  New-Item -ItemType Directory -Path $evidenceDir -Force | Out-Null

  $receiptPresent = if ($isNew) { [bool]($manifest | Where-Object { $_.evidence_category -eq 'RECYCLER_RECEIPT' -and $_.status -eq 'PRESENT' }) } else { [bool]($manifest | Where-Object { $_.category -eq 'RECYCLER_RECEIPT' -and $_.evidence_status -eq 'ACTIVE' }) }
  $processingPresent = if ($isNew) { [bool]($manifest | Where-Object { $_.evidence_category -eq 'PROCESSING_RECOVERY' -and $_.status -eq 'PRESENT' }) } else { [bool]($manifest | Where-Object { $_.category -eq 'PROCESSING_RECOVERY' -and $_.evidence_status -eq 'ACTIVE' }) }

  if ($receiptPresent) {
    $filename = 'recycler_receipt_demo.png'
    Draw-DocumentImage (Join-Path $evidenceDir $filename) 'RECYCLER INTAKE & WEIGHBRIDGE SLIP' 'Destination receipt | Electronic and electrical equipment' @(
      @{ Label = 'Demo reference'; Value = $reference }, @{ Label = 'Recycler facility'; Value = $recycler },
      @{ Label = 'Producer'; Value = $producer }, @{ Label = 'Received net weight'; Value = "$received kg" },
      @{ Label = 'Receipt date'; Value = $receiptDate }, @{ Label = 'Receiving status'; Value = 'Weight recorded at destination' }
    )
    Add-ManifestRow $directory.FullName $filename 'RECYCLER_RECEIPT_IMAGE'
  }
  if ($processingPresent) {
    $filename = 'processing_recovery_demo.png'
    Draw-DocumentImage (Join-Path $evidenceDir $filename) 'PROCESSING & MATERIAL RECOVERY RECORD' 'Recycler-side processing summary | Quantities shown in kilograms' @(
      @{ Label = 'Demo reference'; Value = $reference }, @{ Label = 'Recycler facility'; Value = $recycler },
      @{ Label = 'Input received'; Value = "$received kg" }, @{ Label = 'Processed output'; Value = "$processedOutput kg" },
      @{ Label = 'Recovered material'; Value = "$recovered kg" }, @{ Label = 'Residual waste'; Value = "$residual kg" },
      @{ Label = 'Processing date'; Value = $processingDate }
    )
    Add-ManifestRow $directory.FullName $filename 'PROCESSING_RECOVERY_IMAGE'
  }
  if (-not $receiptPresent -and -not $processingPresent) {
    $filename = 'recycler_facility_profile_demo.png'
    Draw-DocumentImage (Join-Path $evidenceDir $filename) 'RECYCLER FACILITY PROFILE' 'Supporting account document | Does not replace missing shipment or processing evidence' @(
      @{ Label = 'Demo reference'; Value = $reference }, @{ Label = 'Recycler facility'; Value = $recycler },
      @{ Label = 'Associated producer'; Value = $producer }, @{ Label = 'Material stream'; Value = $claim.waste_category },
      @{ Label = 'Claimed received weight'; Value = "$received kg" }, @{ Label = 'Evidence status'; Value = 'Supplemental facility context only' }
    )
    Add-ManifestRow $directory.FullName $filename 'RECYCLER_SUPPORTING_DOCUMENT'
  }

  $readme = Join-Path $directory.FullName 'README.md'
  $addition = "`n`n### Recycler-side evidence`n`nGenerated synthetic recycler-side image evidence is in `evidence/` and indexed in `evidence_manifest.csv`. Missing evidence scenarios remain missing; supplemental facility context does not replace a required receipt or processing record.`n"
  $existing = Get-Content -LiteralPath $readme -Raw
  if ($existing -notmatch '### Recycler-side evidence') { Add-Content -LiteralPath $readme -Value $addition -Encoding utf8 }
}
